"""Health endpoints (REM-07)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from shiptrack.readiness import ReadinessProbe

router = APIRouter()


@router.get("/", response_class=PlainTextResponse)
def root() -> str:
    # Kept for compatibility with legacy's health check and the contract suite.
    return "OK"


@router.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    """Liveness: the process and its event loop respond. Never looks at a dependency."""
    return "ok"


@router.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    probe: ReadinessProbe = request.app.state.readiness
    result = probe.check()
    return JSONResponse(
        {"ready": result.ready, "reason": result.reason}, status_code=200 if result.ready else 503
    )
