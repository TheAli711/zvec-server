"""Collection management endpoints: create, list, inspect, delete, flush, optimize."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from zvec_server.adapter import collections as zcol
from zvec_server.deps import get_manager
from zvec_server.models.collections import (
    CollectionInfo,
    CollectionListResponse,
    CreateCollectionRequest,
)
from zvec_server.models.common import MessageResponse

if TYPE_CHECKING:
    from zvec_server.manager import CollectionManager

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", status_code=201, response_model=CollectionInfo, summary="Create a collection")
async def create_collection(
    req: CreateCollectionRequest,
    manager: CollectionManager = Depends(get_manager),
) -> CollectionInfo:
    """Create a new collection from a vector + scalar field schema."""
    return await run_in_threadpool(manager.create, req)


@router.get("", response_model=CollectionListResponse, summary="List collections")
async def list_collections(
    manager: CollectionManager = Depends(get_manager),
) -> CollectionListResponse:
    """List all registered collections with summary metadata."""
    return await run_in_threadpool(manager.list)


@router.get("/{name}", response_model=CollectionInfo, summary="Get collection info")
async def get_collection(
    name: str,
    manager: CollectionManager = Depends(get_manager),
) -> CollectionInfo:
    """Return a collection's full schema, options, and live statistics."""
    return await run_in_threadpool(manager.info, name)


@router.delete("/{name}", response_model=MessageResponse, summary="Delete a collection")
async def delete_collection(
    name: str,
    manager: CollectionManager = Depends(get_manager),
) -> MessageResponse:
    """Drop a collection and delete its data from disk."""
    await run_in_threadpool(manager.drop, name)
    return MessageResponse(message=f"Collection '{name}' deleted.")


@router.post("/{name}/flush", response_model=MessageResponse, summary="Flush a collection")
async def flush_collection(
    name: str,
    manager: CollectionManager = Depends(get_manager),
) -> MessageResponse:
    """Persist any buffered writes for the collection to disk."""
    managed = manager.get(name)
    await managed.write(zcol.flush_collection)
    return MessageResponse(message=f"Collection '{name}' flushed.")


@router.post("/{name}/optimize", response_model=MessageResponse, summary="Optimize a collection")
async def optimize_collection(
    name: str,
    manager: CollectionManager = Depends(get_manager),
) -> MessageResponse:
    """Run background index optimization (segment merge / index build)."""
    managed = manager.get(name)
    await managed.write(zcol.optimize_collection)
    return MessageResponse(message=f"Collection '{name}' optimized.")
