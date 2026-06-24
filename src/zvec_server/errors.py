"""Application exceptions, the JSON error model, and FastAPI exception handlers.

All server-raised errors derive from :class:`ZvecServerError`, which carries an
HTTP status code and a stable machine-readable ``error_code``. The registered
handlers render every error as a consistent JSON envelope::

    {"error": {"code": "collection_not_found", "message": "...", "details": {...}}}
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

logger = logging.getLogger("zvec_server")


class ZvecServerError(Exception):
    """Base class for all application errors.

    Subclasses set :attr:`status_code` and :attr:`error_code`.
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class CollectionNotFoundError(ZvecServerError):
    status_code = 404
    error_code = "collection_not_found"


class CollectionAlreadyExistsError(ZvecServerError):
    status_code = 409
    error_code = "collection_already_exists"


class CollectionUnavailableError(ZvecServerError):
    """A registered collection exists in metadata but could not be opened on disk."""

    status_code = 503
    error_code = "collection_unavailable"


class SchemaValidationError(ZvecServerError):
    """The requested collection schema is invalid (bad dtype/index/metric, etc.)."""

    status_code = 422
    error_code = "schema_validation_error"


class InvalidArgumentError(ZvecServerError):
    """A request argument was rejected by the server or the Zvec engine."""

    status_code = 400
    error_code = "invalid_argument"


class DocumentNotFoundError(ZvecServerError):
    status_code = 404
    error_code = "document_not_found"


class AuthenticationError(ZvecServerError):
    """The request lacked valid credentials (missing or wrong API key)."""

    status_code = 401
    error_code = "unauthorized"


class ZvecOperationError(ZvecServerError):
    """An operation against the Zvec engine failed."""

    status_code = 500
    error_code = "zvec_operation_error"


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """The JSON envelope returned for every error response."""

    error: ErrorDetail


def build_error_payload(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Render the standard error envelope as a JSON-serializable dict.

    Shared by the exception handlers and the auth middleware (which runs outside
    the exception-handler stack) so every error looks identical on the wire.
    """
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    return body.model_dump(exclude_none=True)


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers that render all errors as the :class:`ErrorResponse` envelope."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(ZvecServerError)
    async def _handle_app_error(request: Request, exc: ZvecServerError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.error_code, exc.message, exc_info=exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=build_error_payload(
                "validation_error",
                "Request validation failed.",
                {"errors": jsonable_encoder(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload("http_error", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content=build_error_payload("internal_error", "An unexpected error occurred."),
        )
