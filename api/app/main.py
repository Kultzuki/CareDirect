from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.cases import router as cases_router
from app.api.demo import router as demo_router
from app.api.documents import router as documents_router
from app.api.estimate_comparison import router as estimate_comparison_router
from app.api.family import router as family_router
from app.api.insurance import router as insurance_router
from app.api.payments import router as payments_router
from app.api.providers import router as providers_router
from app.api.workspace import router as workspace_router
from app.config import get_settings
from app.db import engine
from app.errors import DomainError, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.money import MoneyError

logger = logging.getLogger(__name__)

_UPLOAD_TOKEN_IN_PATH = re.compile(r"(/api/uploads/)[A-Za-z0-9_-]{43}")
_PROVIDER_TOKEN_IN_PATH = re.compile(r"(/api/provider/respond/)[^/?\s]+")
_FAMILY_TOKEN_IN_PATH = re.compile(r"(/api/family/invitations/)[A-Za-z0-9_-]{43}")


def _safe_path(path: str) -> str:
    return _FAMILY_TOKEN_IN_PATH.sub(
        r"\1[redacted]",
        _PROVIDER_TOKEN_IN_PATH.sub(
            r"\1[redacted]", _UPLOAD_TOKEN_IN_PATH.sub(r"\1[redacted]", path)
        ),
    )


class RedactUploadTokens(logging.Filter):
    """An upload link's token travels in the URL path. Keep it out of the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_safe_path(a) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(RedactUploadTokens())

app = FastAPI(title="CareDirect API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-User-Id"],
)


def _err(
    status: int, code: str, message: str, headers: dict[str, str] | None = None, **extra
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": code, "message": message, **extra},
        headers=headers,
    )


@app.middleware("http")
async def payment_privacy_headers(request: Request, call_next):
    response = await call_next(request)
    if any(part in request.url.path for part in ("/payments", "/episode", "/insurance", "/family")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(InvalidTransition)
def _invalid_transition(_r: Request, exc: InvalidTransition):
    return _err(409, "invalid_transition", str(exc), current=exc.current, target=exc.target)


@app.exception_handler(DomainError)
def _domain(_r: Request, exc: DomainError):
    return _err(409, "conflict", str(exc))


@app.exception_handler(ValidationFailed)
def _validation(_r: Request, exc: ValidationFailed):
    return _err(422, "validation_failed", str(exc))


@app.exception_handler(MoneyError)
def _money(_r: Request, exc: MoneyError):
    return _err(422, "invalid_money", str(exc))


@app.exception_handler(NotFound)
def _not_found(_r: Request, exc: NotFound):
    return _err(404, "not_found", str(exc))


@app.exception_handler(Forbidden)
def _forbidden(_r: Request, exc: Forbidden):
    return _err(403, "forbidden", str(exc))


@app.exception_handler(RequestValidationError)
def _request_validation(_r: Request, exc: RequestValidationError):
    # Echo only locations and messages, not submitted values.
    details = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
    return _err(422, "invalid_request", "request validation failed", details=details)


_HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}


@app.exception_handler(StarletteHTTPException)
def _http_exception(_r: Request, exc: StarletteHTTPException):
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return _err(exc.status_code, code, str(exc.detail), headers=exc.headers)


@app.exception_handler(Exception)
def _unhandled(request: Request, exc: Exception):
    # Log server-side; never return exception text to the client.
    logger.error(
        "unhandled error on %s %s (%s)",
        request.method,
        _safe_path(request.url.path),
        type(exc).__name__,
    )
    return _err(500, "internal_error", "internal server error")


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return {"status": "ok", "database": "ok"}


app.include_router(cases_router)
app.include_router(documents_router)
app.include_router(estimate_comparison_router)
app.include_router(insurance_router)
app.include_router(family_router)
app.include_router(providers_router)

app.include_router(payments_router)
app.include_router(workspace_router)
app.include_router(demo_router)
