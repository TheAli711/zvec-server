"""Shared API models for health, readiness, and simple message responses.

These models are intentionally tiny; they exist so every endpoint returns a
typed, documented JSON body that shows up cleanly in the OpenAPI schema.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zvec_server.errors import ErrorResponse

__all__ = [
    "ErrorResponse",
    "HealthResponse",
    "MessageResponse",
    "ReadyResponse",
]


class HealthResponse(BaseModel):
    """Liveness probe payload.

    Returned by ``GET /healthz``. A ``200`` with ``status == "ok"`` means the
    process is up and serving requests; it does not imply collections are loaded.
    """

    status: str = Field(default="ok", description='Always ``"ok"`` when the process is alive.')

    model_config = {
        "json_schema_extra": {"examples": [{"status": "ok"}]},
    }


class ReadyResponse(BaseModel):
    """Readiness probe payload.

    Returned by ``GET /readyz``. Reports how many collections were opened
    successfully versus registered-but-unavailable (e.g. their on-disk data is
    missing). The endpoint returns ``200`` even when some collections are
    unavailable so that a partial-but-serving instance is still considered ready.
    """

    status: str = Field(description='``"ready"`` when the application has finished startup.')
    collections_loaded: int = Field(
        description="Number of collections successfully opened and serving."
    )
    collections_unavailable: int = Field(
        default=0,
        description="Number of registered collections that could not be opened on disk.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"status": "ready", "collections_loaded": 3, "collections_unavailable": 0}]
        },
    }


class MessageResponse(BaseModel):
    """Generic acknowledgement returned by mutating endpoints (delete/flush/optimize)."""

    message: str = Field(description="Human-readable description of the action taken.")

    model_config = {
        "json_schema_extra": {"examples": [{"message": "Collection 'articles' deleted."}]},
    }
