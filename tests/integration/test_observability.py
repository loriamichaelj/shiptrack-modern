"""REM-08 and REM-15: request IDs, structured access logs, and metrics."""

import json
import logging
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from shiptrack import metrics
from shiptrack.api import shipments
from shiptrack.config import Settings
from shiptrack.logconfig import configure_logging
from shiptrack.main import create_app

MakeShipment = Callable[..., dict[str, Any]]


def exposition() -> str:
    return generate_latest().decode()


def test_a_request_id_is_generated_and_returned(client: TestClient) -> None:
    first = client.get("/api/v1/shipments").headers["x-request-id"]
    second = client.get("/api/v1/shipments").headers["x-request-id"]
    assert uuid.UUID(first) != uuid.UUID(second)


def test_the_callers_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/api/v1/shipments", headers={"X-Request-Id": "caller-123"})
    assert response.headers["x-request-id"] == "caller-123"


def test_the_load_balancers_trace_id_is_the_fallback(client: TestClient) -> None:
    trace = "Root=1-67891233-abcdef012345678912345678"
    response = client.get("/api/v1/shipments", headers={"X-Amzn-Trace-Id": trace})
    assert response.headers["x-request-id"] == trace
    both = client.get(
        "/api/v1/shipments", headers={"X-Request-Id": "mine", "X-Amzn-Trace-Id": trace}
    )
    assert both.headers["x-request-id"] == "mine"


def test_the_stack_header_is_on_every_response(client: TestClient) -> None:
    for response in (
        client.get("/"),
        client.get("/api/v1/shipments"),
        client.get("/api/v1/track/MF0000000000"),  # 404
        client.post("/api/v1/shipments", json={}),  # 422
    ):
        assert response.headers["x-shiptrack-stack"] == "modern"


def test_an_unhandled_error_still_carries_the_headers(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(shipments, "get_shipment_or_404", boom)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get(f"/api/v1/shipments/{uuid.uuid4()}")
    assert response.status_code == 500
    assert response.headers["x-shiptrack-stack"] == "modern"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_the_error_envelope_quotes_the_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/track/MF0000000000", headers={"X-Request-Id": "quote-me"})
    assert response.json()["error"]["request_id"] == "quote-me"


def records(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, Any]]:
    found = []
    for record in caplog.records:
        if isinstance(record.msg, dict) and record.msg.get("event") == event:
            found.append(record.msg)
    return found


def test_a_request_is_logged_with_its_context(
    client: TestClient, make_shipment: MakeShipment, caplog: pytest.LogCaptureFixture
) -> None:
    shipment = make_shipment()
    with caplog.at_level(logging.INFO, logger="shiptrack.http"):
        client.get(f"/api/v1/shipments/{shipment['id']}", headers={"X-Request-Id": "log-me"})
    entry = records(caplog, "request")[-1]
    assert entry["request_id"] == "log-me"
    assert entry["route"] == "/api/v1/shipments/{shipment_id}"
    assert entry["method"] == "GET"
    assert entry["status"] == 200
    assert entry["shipment_id"] == shipment["id"]
    assert isinstance(entry["duration_ms"], float)


def test_health_checks_are_not_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="shiptrack.http"):
        for path in ("/", "/healthz", "/readyz"):
            client.get(path)
    assert records(caplog, "request") == []


def test_log_lines_are_json_with_the_design_s_fields(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")  # bind the handler to the stdout capsys is capturing
    client.get("/api/v1/shipments")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if '"event": "request"' in ln]
    assert lines
    entry = json.loads(lines[-1])
    assert {"ts", "level", "event", "logger", "request_id", "route", "method", "status"} <= set(
        entry
    )
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+Z", entry["ts"])


def test_passwords_never_reach_the_logs(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.get_logger("shiptrack.test").info("connecting", password="hunter2", user="app")
    out = capsys.readouterr().out
    assert "hunter2" not in out and '"user": "app"' in out


def test_the_route_label_is_the_template_not_the_raw_path(
    client: TestClient, make_shipment: MakeShipment
) -> None:
    shipment = make_shipment()
    client.get(f"/api/v1/shipments/{shipment['id']}")
    client.get(f"/api/v1/track/{shipment['tracking_number']}")
    text = exposition()
    assert 'route="/api/v1/shipments/{shipment_id}"' in text
    assert 'route="/api/v1/track/{tracking_number}"' in text
    assert shipment["id"] not in text
    assert shipment["tracking_number"] not in text


def test_requests_are_counted_by_status_class(client: TestClient) -> None:
    def count(status_class: str) -> float:
        value = metrics.HTTP_REQUESTS.labels(
            route="/api/v1/track/{tracking_number}", method="GET", status_class=status_class
        )._value.get()
        return float(value)

    before = count("4xx")
    client.get("/api/v1/track/MF0000000000")
    assert count("4xx") == before + 1


def test_a_latency_histogram_is_kept_per_route(client: TestClient) -> None:
    client.get("/api/v1/shipments")
    assert (
        'http_request_duration_seconds_bucket{le="0.005",method="GET",route="/api/v1/shipments"}'
        in exposition()
    )


def test_metrics_are_not_served_on_the_api_port(client: TestClient) -> None:
    assert client.get("/metrics").status_code == 404


def test_the_pool_gauge_and_the_design_s_metrics_exist(client: TestClient) -> None:
    client.get("/api/v1/shipments")
    text = exposition()
    for name in (
        "shiptrack_db_pool_checked_out",
        "shiptrack_events_enqueued_total",
        "shiptrack_events_processed_total",
        "shiptrack_event_apply_lag_seconds",
        "shiptrack_notifications_sent_total",
        "shiptrack_sla_breaches_total",
        "shiptrack_pod_uploads_total",
    ):
        assert f"# TYPE {name}" in text


def test_enqueue_results_are_counted(client: TestClient, make_shipment: MakeShipment) -> None:
    shipment = make_shipment()
    ok = metrics.EVENTS_ENQUEUED.labels(result="ok")
    before = ok._value.get()
    response = client.post(
        f"/api/v1/shipments/{shipment['id']}/events",
        headers={"Idempotency-Key": "m-1"},
        json={"event_type": "PICKED_UP", "location": "X", "occurred_at": "2026-10-01T00:00:00Z"},
    )
    assert response.status_code == 202
    assert ok._value.get() == before + 1
