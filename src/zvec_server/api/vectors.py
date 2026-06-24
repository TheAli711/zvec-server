"""Document endpoints: insert/upsert/update, delete, fetch, and similarity search."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from zvec_server.adapter import operations
from zvec_server.deps import get_manager
from zvec_server.errors import DocumentNotFoundError
from zvec_server.models.search import SearchRequest, SearchResponse
from zvec_server.models.vectors import (
    DeleteRequest,
    DeleteResponse,
    DocOut,
    FetchRequest,
    FetchResponse,
    WriteRequest,
    WriteResponse,
)

if TYPE_CHECKING:
    from zvec_server.manager import CollectionManager

router = APIRouter(prefix="/collections/{name}", tags=["documents"])


@router.post("/docs/insert", response_model=WriteResponse, summary="Insert documents")
async def insert_docs(
    name: str,
    body: WriteRequest,
    manager: CollectionManager = Depends(get_manager),
) -> WriteResponse:
    """Insert new documents. Ids are auto-generated when omitted."""
    managed = manager.get(name)
    return await managed.write(lambda c: operations.insert(c, body.docs, "insert"))


@router.post("/docs/upsert", response_model=WriteResponse, summary="Upsert documents")
async def upsert_docs(
    name: str,
    body: WriteRequest,
    manager: CollectionManager = Depends(get_manager),
) -> WriteResponse:
    """Insert documents, replacing any existing ones with the same id."""
    managed = manager.get(name)
    return await managed.write(lambda c: operations.insert(c, body.docs, "upsert"))


@router.post("/docs/update", response_model=WriteResponse, summary="Update documents")
async def update_docs(
    name: str,
    body: WriteRequest,
    manager: CollectionManager = Depends(get_manager),
) -> WriteResponse:
    """Partially update existing documents by id."""
    managed = manager.get(name)
    return await managed.write(lambda c: operations.insert(c, body.docs, "update"))


@router.post("/docs/delete", response_model=DeleteResponse, summary="Delete documents")
async def delete_docs(
    name: str,
    body: DeleteRequest,
    manager: CollectionManager = Depends(get_manager),
) -> DeleteResponse:
    """Delete documents by id list or by a SQL-like filter (exactly one)."""
    managed = manager.get(name)
    return await managed.write(lambda c: operations.delete(c, body))


@router.post("/docs/fetch", response_model=FetchResponse, summary="Fetch documents by id")
async def fetch_docs(
    name: str,
    body: FetchRequest,
    manager: CollectionManager = Depends(get_manager),
) -> FetchResponse:
    """Fetch documents by id. Missing ids are omitted from the response."""
    managed = manager.get(name)
    return await managed.read(lambda c: operations.fetch(c, body))


@router.get("/docs/{doc_id}", response_model=DocOut, summary="Fetch a single document")
async def get_doc(
    name: str,
    doc_id: str,
    include_vector: bool = False,
    output_fields: list[str] | None = Query(default=None),
    manager: CollectionManager = Depends(get_manager),
) -> DocOut:
    """Fetch one document by id, returning ``404`` if it does not exist."""
    managed = manager.get(name)
    req = FetchRequest(ids=[doc_id], output_fields=output_fields, include_vector=include_vector)
    result = await managed.read(lambda c: operations.fetch(c, req))
    doc = result.docs.get(doc_id)
    if doc is None:
        raise DocumentNotFoundError(
            f"Document '{doc_id}' not found in collection '{name}'.",
            {"collection": name, "id": doc_id},
        )
    return doc


@router.post("/search", response_model=SearchResponse, summary="Vector similarity search")
async def search(
    name: str,
    body: SearchRequest,
    manager: CollectionManager = Depends(get_manager),
) -> SearchResponse:
    """Run one or more nearest-neighbour queries with an optional filter."""
    managed = manager.get(name)
    return await managed.read(lambda c: operations.search(c, body))
