"""One error vocabulary and one JSON error shape: {"error": {"code", "message", ...}}."""

import psycopg
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout, TooManyRequests

log = structlog.get_logger()


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, fields: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"


def describe_validation_errors(errors: list) -> list[dict[str, str]]:
    """Field and problem type only: never echo the submitted value back."""
    return [{"field": ".".join(str(p) for p in e["loc"]), "problem": e["type"]} for e in errors]


def _body(code: str, message: str, fields: list[dict[str, str]] | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, Unauthorized) else None
        return JSONResponse(
            _body(exc.code, exc.message, exc.fields), status_code=exc.status_code, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = describe_validation_errors(exc.errors())
        return JSONResponse(_body("validation_error", "Invalid request", fields), status_code=422)

    @app.exception_handler(psycopg.OperationalError)
    async def handle_database_trouble(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
        """Both cases are 503 so a webhook provider redelivers; nothing was acknowledged."""
        if isinstance(exc, PoolTimeout | TooManyRequests):
            log.warning("db_pool_exhausted", error=type(exc).__name__)
            body = _body("overloaded", "Server busy, retry shortly")
        else:
            log.error("database_unavailable", error=type(exc).__name__)
            body = _body("service_unavailable", "Database unavailable")
        return JSONResponse(body, status_code=503, headers={"Retry-After": "1"})

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", exc_info=exc)
        return JSONResponse(_body("internal_error", "Internal error"), status_code=500)
