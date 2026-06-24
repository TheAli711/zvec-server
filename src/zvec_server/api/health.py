"""Liveness and readiness probe endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from zvec_server.models.common import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    """Return ``200`` while the process is alive and serving requests."""
    return HealthResponse()


@router.get("/readyz", response_model=ReadyResponse, summary="Readiness probe")
async def readyz(request: Request) -> ReadyResponse:
    """Report readiness and how many collections are loaded vs. unavailable.

    Returns ``503`` until application startup has completed.
    """
    ready = getattr(request.app.state, "ready", False)
    manager = getattr(request.app.state, "manager", None)
    if not ready or manager is None:
        raise HTTPException(status_code=503, detail="Service not ready.")
    loaded, unavailable = manager.counts()
    return ReadyResponse(
        status="ready",
        collections_loaded=loaded,
        collections_unavailable=unavailable,
    )
