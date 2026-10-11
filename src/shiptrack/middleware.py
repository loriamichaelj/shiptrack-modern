"""Request middleware: request IDs, the stack header, security headers, access logs, metrics, and
the game-day fault injector (REM-08, REM-15, REM-16, design 5.9).

These are plain ASGI middleware, not BaseHTTPMiddleware, so they add no per-request task and never
buffer a streamed body.
"""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from typing import Any

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shiptrack import metrics
from shiptrack.config import Settings

log = structlog.get_logger("shiptrack.http")

# Health checks are polled every few seconds by the ALB and Kubernetes: no access log, no noise.
HEALTH_PATHS = frozenset({"/", "/healthz", "/readyz"})

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
    "object-src 'none'"
)


def security_headers(hsts: bool) -> dict[str, str]:
    headers = {
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }
    if hsts:
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return headers


def route_template(scope: Scope) -> str:
    """The route's template, never the raw path: a raw path is a metric series per shipment."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        # "/ui/{path:path}" -> "/ui/{path}": the converter is routing detail, not part of the name.
        return re.sub(r"\{(\w+):\w+\}", r"{\1}", str(path))
    raw = scope.get("path", "")
    if raw.startswith("/ui/assets/"):
        return "/ui/assets/{file}"
    if raw == "/ui" or raw.startswith("/ui/"):
        return "/ui/{path}"
    return "unmatched"


def _internal_error(request_id: str) -> ASGIApp:
    body = json.dumps(
        {
            "error": {
                "code": "INTERNAL",
                "message": "Internal server error",
                "request_id": request_id,
            }
        }
    ).encode()

    async def respond(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return respond


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self._security = security_headers(settings.hsts_enabled)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = (
            headers.get("x-request-id") or headers.get("x-amzn-trace-id") or str(uuid.uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        status = {"code": 500}
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                status["code"] = message["status"]
                out = MutableHeaders(scope=message)
                out["X-Request-Id"] = request_id
                out["X-ShipTrack-Stack"] = "modern"
                for name, value in self._security.items():
                    out[name] = value
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_headers)
            except Exception:
                # Starlette would build this 500 outside this middleware, without our headers; the
                # contract suite reads a missing stack header as routing fall-through.
                log.exception("unhandled_error")
                if response_started:
                    raise
                await _internal_error(request_id)(scope, receive, send_with_headers)
        finally:
            elapsed = time.perf_counter() - started
            route = route_template(scope)
            method = scope["method"]
            metrics.HTTP_REQUESTS.labels(
                route=route, method=method, status_class=f"{status['code'] // 100}xx"
            ).inc()
            metrics.HTTP_DURATION.labels(route=route, method=method).observe(elapsed)
            if scope.get("path") not in HEALTH_PATHS:
                path_params = scope.get("path_params") or {}
                extra = (
                    {"shipment_id": path_params["shipment_id"]}
                    if "shipment_id" in path_params
                    else {}
                )
                log.info(
                    "request",
                    route=route,
                    method=method,
                    status=status["code"],
                    duration_ms=round(elapsed * 1000, 1),
                    **extra,
                )
            structlog.contextvars.clear_contextvars()


class FaultInjectionMiddleware:
    """Game days only: fail a fraction of non-health requests with a 500 INJECTED_FAULT."""

    def __init__(self, app: ASGIApp, rate: float, rng: random.Random | None = None) -> None:
        self.app = app
        self._rate = rate
        self._rng = rng or random.Random()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and self._rate > 0
            and scope.get("path") not in HEALTH_PATHS
            and self._rng.random() < self._rate
        ):
            request_id = scope.get("state", {}).get("request_id")
            body = json.dumps(
                {
                    "error": {
                        "code": "INJECTED_FAULT",
                        "message": "Injected fault (game day)",
                        "request_id": request_id,
                    }
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def as_dict(headers: Any) -> dict[str, str]:  # small helper for tests
    return {k.lower(): v for k, v in headers.items()}
