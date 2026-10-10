"""The operations server on port 9090 (REM-15): /metrics for the managed Prometheus scraper, and
/healthz for the workers. It is separate from port 8000 on purpose: the ALB forwards everything on
8000, so /metrics there would be public."""

from __future__ import annotations

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def make_handler(healthy: Callable[[], bool]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/metrics":
                body = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            elif self.path == "/healthz":
                ok = healthy()
                body = b"ok" if ok else b"stalled"
                self.send_response(200 if ok else 503)
                self.send_header("Content-Type", "text/plain")
            else:
                body = b"not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return  # probes and scrapes are not logged

    return Handler


def start_ops_server(
    port: int,
    healthy: Callable[[], bool] = lambda: True,
    host: str = "0.0.0.0",
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(healthy))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="ops-server", daemon=True).start()
    return server
