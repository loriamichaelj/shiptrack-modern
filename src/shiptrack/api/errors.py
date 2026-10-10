"""Error envelope and exception handlers.

Every 4xx/5xx response, including validation errors, uses:
    {"error": {"code": "...", "message": "...", "request_id": "<id of the request>"}}
Legacy sent null for request_id; modern fills it in so a caller can quote it.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger("shiptrack.errors")

_STATUS_CODES = {404: "NOT_FOUND", 422: "VALIDATION_ERROR"}


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def not_found(message: str = "Not found") -> ApiError:
    return ApiError(404, "NOT_FOUND", message)


def _envelope(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"] if part != "body")
        parts.append(f"{location}: {err['msg']}" if location else str(err["msg"]))
    return "; ".join(parts) or "Invalid request"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _envelope(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(request, 422, "VALIDATION_ERROR", _validation_message(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        fallback = "INTERNAL" if exc.status_code >= 500 else "VALIDATION_ERROR"
        code = _STATUS_CODES.get(exc.status_code, fallback)
        return _envelope(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error=type(exc).__name__)
        return _envelope(request, 500, "INTERNAL", "Internal server error")
