"""The root health check and the error envelope."""

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from shiptrack.config import Settings
from shiptrack.main import create_app
from tests.integration.conftest import create_db_secret


def test_health_returns_ok_as_plain_text(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers["content-type"].startswith("text/plain")


def test_root_stays_green_while_the_database_is_unreachable(settings: Settings) -> None:
    """`/` is kept for compatibility and never looks at dependencies; /readyz is the real check."""
    unreachable = make_url("postgresql+psycopg://u:p@127.0.0.1:1/shiptrack")
    broken = settings.model_copy(update={"db_secret_arn": create_db_secret(unreachable)})
    with TestClient(create_app(broken), raise_server_exceptions=False) as client:
        assert client.get("/").status_code == 200
        response = client.get("/api/v1/shipments")
    assert response.status_code == 500
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("INTERNAL", "Internal server error")
    assert error["request_id"] == response.headers["x-request-id"]


def test_unknown_route_uses_the_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_uses_the_envelope(client: TestClient) -> None:
    response = client.delete("/api/v1/shipments")
    assert response.status_code == 405
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


def test_openapi_and_docs_are_not_exposed(client: TestClient) -> None:
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404
