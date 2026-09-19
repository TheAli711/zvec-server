"""Document endpoints: insert/upsert/update, delete, fetch, and similarity search."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from zvec_server.adapter import operations
from zvec_server.deps import get_manager
from zvec_server.errors import DocumentNotFoundError, ZvecServerError, build_error_payload
from zvec_server.models.search import (
    GroupSearchRequest,
    GroupSearchResponse,
    SearchRequest,
    SearchResponse,
)
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

# Documents read per lock acquisition while exporting.
EXPORT_BATCH_SIZE = 500


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


@router.post(
    "/search/group-by",
    response_model=GroupSearchResponse,
    summary="Vector search grouped by a scalar field",
)
async def group_search(
    name: str,
    body: GroupSearchRequest,
    manager: CollectionManager = Depends(get_manager),
) -> GroupSearchResponse:
    """Return the best hits per group, e.g. the top chunks from each top document."""
    managed = manager.get(name)
    return await managed.read(lambda c: operations.group_search(c, body))


def _ndjson_lines(batch: list[DocOut]) -> str:
    # Each line is shaped like a DocIn (no score), so an export can be fed
    # straight back into /docs/insert.
    return "".join(
        doc.model_dump_json(exclude={"score"}, exclude_none=True) + "\n" for doc in batch
    )


async def _ndjson_stream(
    first: list[DocOut], batches: AsyncIterator[list[DocOut]]
) -> AsyncIterator[str]:
    try:
        if first:
            yield _ndjson_lines(first)
        async for batch in batches:
            yield _ndjson_lines(batch)
    except ZvecServerError as exc:
        # Headers are already sent, so report the failure in-band as a final line.
        yield json.dumps(build_error_payload(exc.error_code, exc.message, exc.details)) + "\n"


@router.get(
    "/export",
    response_class=StreamingResponse,
    summary="Export every document as NDJSON",
    responses={
        200: {
            "content": {"application/x-ndjson": {}},
            "description": "One JSON document per line, in DocIn shape.",
        }
    },
)
async def export_docs(
    name: str,
    include_vector: bool = True,
    output_fields: list[str] | None = Query(default=None),
    manager: CollectionManager = Depends(get_manager),
) -> StreamingResponse:
    """Stream a consistent snapshot of every document, one JSON object per line.

    Writes made after the export starts are not included. If the export is cut
    short (e.g. the collection is dropped), the last line is an error envelope
    ``{"error": {...}}`` rather than a document.
    """
    managed = manager.get(name)
    batches = managed.stream(
        lambda c: operations.open_export(c, output_fields, include_vector), EXPORT_BATCH_SIZE
    )
    # Read the first batch before responding so bad input (e.g. an unknown
    # output field) is a normal JSON error rather than a broken stream.
    first: list[DocOut] = await anext(batches, [])
    return StreamingResponse(_ndjson_stream(first, batches), media_type="application/x-ndjson")
