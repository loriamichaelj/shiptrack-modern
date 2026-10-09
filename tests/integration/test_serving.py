"""REM-16 and REM-15: security headers, UI serving, fault injection, and the operations port."""

import socket
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from shiptrack.api.ui import has_inline_code
from shiptrack.config import Settings
from shiptrack.main import create_app
from shiptrack.middleware import CSP, security_headers
from shiptrack.ops import start_ops_server

SHELL = (
    '<!doctype html><html><head><script type="module" src="/ui/assets/app-abc123.js"></script>'
    "</head></html>"
)


@pytest.fixture()
def web_dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(SHELL)
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log('ui')")
    return tmp_path


@pytest.fixture()
def ui_client(settings: Settings, web_dist: Path) -> Iterator[TestClient]:
    with TestClient(create_app(settings.model_copy(update={"web_dist": web_dist}))) as client:
        yield client


def test_security_headers_are_on_every_response(client: TestClient) -> None:
    for response in (client.get("/"), client.get("/api/v1/shipments"), client.get("/api/v1/x")):
        assert response.headers["content-security-policy"] == CSP
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_the_csp_allows_no_inline_code_and_no_framing() -> None:
    assert "script-src 'self'" in CSP
    assert "style-src 'self'" in CSP
    assert "unsafe-inline" not in CSP and "unsafe-eval" not in CSP
    assert "frame-ancestors 'none'" in CSP


def test_hsts_is_sent_only_for_an_https_base_url(settings: Settings) -> None:
    assert "Strict-Transport-Security" not in security_headers(False)
    assert security_headers(True)["Strict-Transport-Security"].startswith("max-age=")

    with TestClient(create_app(settings)) as plain:
        assert "strict-transport-security" not in plain.get("/").headers
    secure = settings.model_copy(update={"base_url": "https://shiptrack.example.com"})
    with TestClient(create_app(secure)) as client:
        assert "strict-transport-security" in client.get("/").headers


def test_the_shell_is_served_uncached(ui_client: TestClient) -> None:
    for path in ("/ui", "/ui/", "/ui/shipments/abc", "/ui/anything/deep/link"):
        response = ui_client.get(path)
        assert response.status_code == 200, path
        assert response.text == SHELL
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["content-type"].startswith("text/html")


def test_hashed_assets_are_immutable(ui_client: TestClient) -> None:
    response = ui_client.get("/ui/assets/app-abc123.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.text == "console.log('ui')"


def test_a_missing_asset_is_a_404_not_the_shell(ui_client: TestClient) -> None:
    response = ui_client.get("/ui/assets/nope.js")
    assert response.status_code == 404
    assert response.headers.get("cache-control") != "public, max-age=31536000, immutable"


def test_the_ui_does_not_shadow_the_api(ui_client: TestClient) -> None:
    assert ui_client.get("/api/v1/shipments").status_code == 200
    assert ui_client.get("/").text == "OK"


def test_the_api_starts_without_a_built_ui(client: TestClient) -> None:
    assert client.get("/ui").status_code == 404
    assert client.get("/api/v1/shipments").status_code == 200


def test_ui_requests_use_a_templated_route_label(ui_client: TestClient) -> None:
    ui_client.get("/ui/shipments/some-id")
    ui_client.get("/ui/assets/app-abc123.js")
    text = generate_latest().decode()
    assert 'route="/ui/{path}"' in text
    assert 'route="/ui/assets/{file}"' in text
    assert "some-id" not in text


def test_inline_code_in_a_built_shell_is_detected() -> None:
    assert has_inline_code(SHELL) == []
    assert has_inline_code("<script>alert(1)</script>") == ["inline <script>"]
    assert has_inline_code('<script type="module">x()</script>') == ["inline <script>"]
    assert has_inline_code("<style>a{}</style>") == ["inline <style>"]
    assert has_inline_code('<link rel="stylesheet" href="/a.css">') == []


def test_a_fault_rate_of_one_fails_every_api_request(settings: Settings) -> None:
    broken = settings.model_copy(update={"fault_error_rate": 1.0})
    with TestClient(create_app(broken)) as client:
        response = client.get("/api/v1/shipments", headers={"X-Request-Id": "game-day"})
        assert response.status_code == 500
        error = response.json()["error"]
        assert error["code"] == "INJECTED_FAULT"
        assert error["request_id"] == "game-day"
        assert response.headers["x-shiptrack-stack"] == "modern"
        assert response.headers["x-request-id"] == "game-day"


def test_faults_never_touch_the_health_checks(settings: Settings) -> None:
    broken = settings.model_copy(update={"fault_error_rate": 1.0})
    with TestClient(create_app(broken)) as client:
        for path in ("/", "/healthz", "/readyz"):
            assert client.get(path).status_code == 200, path


def test_a_fault_rate_of_zero_injects_nothing(client: TestClient) -> None:
    assert all(client.get("/api/v1/shipments").status_code == 200 for _ in range(20))


def test_a_fractional_fault_rate_fails_roughly_that_share(settings: Settings) -> None:
    flaky = settings.model_copy(update={"fault_error_rate": 0.5})
    with TestClient(create_app(flaky)) as client:
        failures = sum(client.get("/api/v1/shipments").status_code == 500 for _ in range(200))
    assert 50 < failures < 150


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch(port: int, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def test_the_ops_server_serves_metrics_and_health() -> None:
    port = free_port()
    server = start_ops_server(port, host="127.0.0.1")
    try:
        status, body = fetch(port, "/metrics")
        assert status == 200
        assert "# TYPE http_requests_total counter" in body
        assert fetch(port, "/healthz") == (200, "ok")
        assert fetch(port, "/anything")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


def test_the_ops_health_follows_the_workers_liveness() -> None:
    port = free_port()
    alive = {"ok": True}
    server = start_ops_server(port, lambda: alive["ok"], host="127.0.0.1")
    try:
        assert fetch(port, "/healthz")[0] == 200
        alive["ok"] = False
        assert fetch(port, "/healthz") == (503, "stalled")
    finally:
        server.shutdown()
        server.server_close()
