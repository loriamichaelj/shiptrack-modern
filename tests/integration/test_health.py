"""REM-07: liveness never looks at dependencies; readiness does."""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from shiptrack import readiness as readiness_module
from shiptrack.config import Settings
from shiptrack.main import create_app
from tests.integration.conftest import create_db_secret


def broken_settings(settings: Settings) -> Settings:
    unreachable = make_url("postgresql+psycopg://u:p@127.0.0.1:1/shiptrack")
    return settings.model_copy(update={"db_secret_arn": create_db_secret(unreachable)})


def test_healthz_is_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_healthz_ignores_a_dead_database(settings: Settings) -> None:
    with TestClient(create_app(broken_settings(settings))) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 200


def test_readyz_is_ready_with_a_healthy_database(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "reason": "ok"}


def test_readyz_fails_without_a_database(settings: Settings) -> None:
    with TestClient(create_app(broken_settings(settings))) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"ready": False, "reason": "database_unavailable"}


def test_readyz_fails_while_draining(client: TestClient) -> None:
    client.app.state.readiness.drain()  # type: ignore[attr-defined]
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["reason"] == "draining"
    # Liveness is unaffected, so Kubernetes does not kill a pod that is finishing its requests.
    assert client.get("/healthz").status_code == 200


def test_readyz_can_be_forced_to_fail_for_a_game_day(settings: Settings) -> None:
    forced = settings.model_copy(update={"fault_ready_fail": True})
    with TestClient(create_app(forced)) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["reason"] == "fault_injected"
        assert client.get("/healthz").status_code == 200


def test_an_unknown_schema_revision_is_not_ready_and_is_logged(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    other = settings.model_copy(update={"schema_compat": "0002,0003"})
    with (
        caplog.at_level("ERROR", logger="shiptrack.ready"),
        TestClient(create_app(other)) as client,
    ):
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["reason"] == "schema_incompatible"
    assert any("schema_incompatible" in record.message for record in caplog.records)


def test_a_tolerated_revision_among_several_is_ready(settings: Settings) -> None:
    several = settings.model_copy(update={"schema_compat": "0001,0002"})
    with TestClient(create_app(several)) as client:
        assert client.get("/readyz").status_code == 200


def test_the_answer_is_cached_for_two_seconds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = client.app.state.readiness  # type: ignore[attr-defined]
    queries: list[int] = []
    real = probe._query_revision

    def counting() -> Any:
        queries.append(1)
        return real()

    monkeypatch.setattr(probe, "_query_revision", counting)
    for _ in range(5):
        assert client.get("/readyz").status_code == 200
    assert len(queries) == 1

    later = time.monotonic() + readiness_module.CACHE_SECONDS + 0.1
    monkeypatch.setattr(readiness_module.time, "monotonic", lambda: later)
    assert client.get("/readyz").status_code == 200
    assert len(queries) == 2


def test_a_slow_database_is_not_ready(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = client.app.state.readiness  # type: ignore[attr-defined]
    monkeypatch.setattr(readiness_module, "PROBE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(probe, "_query_revision", lambda: time.sleep(1.0))
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["reason"] == "database_timeout"
