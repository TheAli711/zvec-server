"""High-level document operations over an open ``zvec.Collection``.

Each function accepts/returns our API models and translates engine failures:

* Zvec ``ValueError`` (e.g. a malformed filter) -> :class:`InvalidArgumentError`.
* Any other unexpected engine exception -> :class:`ZvecOperationError`.
* Our own :class:`ZvecServerError` subclasses propagate unchanged.

These functions perform no locking or threadpool offload; callers higher up the
stack own concurrency control.
"""

from __future__ import annotations

from typing import Literal

import zvec

from zvec_server.adapter import doc_mapper, query_mapper
from zvec_server.errors import (
    InvalidArgumentError,
    ZvecOperationError,
    ZvecServerError,
)
from zvec_server.models.search import SearchRequest, SearchResponse
from zvec_server.models.vectors import (
    DeleteRequest,
    DeleteResponse,
    DocIn,
    FetchRequest,
    FetchResponse,
    WriteResponse,
)

__all__ = ["delete", "fetch", "insert", "search"]

WriteMode = Literal["insert", "upsert", "update"]


def insert(
    collection: zvec.Collection,
    docs: list[DocIn],
    mode: WriteMode = "insert",
) -> WriteResponse:
    """Write documents to a collection.

    Args:
        collection: The open collection.
        docs: Documents to write (ids auto-generated when omitted).
        mode: ``insert``, ``upsert``, or ``update``.

    Returns:
        A :class:`WriteResponse` with per-document status.

    Raises:
        InvalidArgumentError: If the engine rejects the documents.
        ZvecOperationError: For any other engine failure.
    """
    zvec_docs, ids = doc_mapper.to_zvec_docs(docs)
    op = {
        "insert": collection.insert,
        "upsert": collection.upsert,
        "update": collection.update,
    }[mode]
    try:
        statuses = op(zvec_docs)
    except ZvecServerError:
        raise
    except ValueError as exc:
        raise InvalidArgumentError(f"Invalid document(s) for {mode}: {exc}") from exc
    except Exception as exc:
        raise ZvecOperationError(f"Failed to {mode} documents: {exc}") from exc
    return doc_mapper.build_write_response(ids, statuses)


def delete(collection: zvec.Collection, req: DeleteRequest) -> DeleteResponse:
    """Delete documents by id or by filter.

    Exactly one of ``req.ids`` / ``req.filter`` is set (enforced by the model).

    Raises:
        InvalidArgumentError: If a filter is malformed.
        ZvecOperationError: For any other engine failure.
    """
    if req.ids is not None:
        try:
            statuses = collection.delete(req.ids)
        except ZvecServerError:
            raise
        except ValueError as exc:
            raise InvalidArgumentError(f"Invalid delete request: {exc}") from exc
        except Exception as exc:
            raise ZvecOperationError(f"Failed to delete documents: {exc}") from exc
        results = [
            doc_mapper.status_to_item(doc_id, status)
            for doc_id, status in zip(req.ids, statuses, strict=False)
        ]
        ok = all(item.ok for item in results)
        return DeleteResponse(ok=ok, results=results)

    # filter-based delete
    assert req.filter is not None  # model guarantees exactly-one-of
    try:
        collection.delete_by_filter(req.filter)
    except ZvecServerError:
        raise
    except ValueError as exc:
        raise InvalidArgumentError(f"Invalid delete filter: {exc}", {"filter": req.filter}) from exc
    except Exception as exc:
        raise ZvecOperationError(f"Failed to delete by filter: {exc}") from exc
    return DeleteResponse(ok=True, filter=req.filter, message="Deleted by filter.")


def fetch(collection: zvec.Collection, req: FetchRequest) -> FetchResponse:
    """Fetch documents by id.

    Missing ids are simply absent from the response.

    Raises:
        InvalidArgumentError: If the request is rejected by the engine.
        ZvecOperationError: For any other engine failure.
    """
    try:
        found = collection.fetch(
            req.ids,
            output_fields=req.output_fields,
            include_vector=req.include_vector,
        )
    except ZvecServerError:
        raise
    except ValueError as exc:
        raise InvalidArgumentError(f"Invalid fetch request: {exc}") from exc
    except Exception as exc:
        raise ZvecOperationError(f"Failed to fetch documents: {exc}") from exc

    docs = {
        doc_id: doc_mapper.from_zvec_doc(doc, include_vector=req.include_vector)
        for doc_id, doc in found.items()
    }
    return FetchResponse(docs=docs)


def search(collection: zvec.Collection, req: SearchRequest) -> SearchResponse:
    """Run one or more nearest-neighbour queries.

    Raises:
        InvalidArgumentError: If a filter or query is malformed.
        ZvecOperationError: For any other engine failure.
    """
    queries = query_mapper.build_queries(req.queries)
    try:
        hits = collection.query(
            queries=queries,
            topk=req.topk,
            filter=req.filter,
            include_vector=req.include_vector,
            output_fields=req.output_fields,
        )
    except ZvecServerError:
        raise
    except ValueError as exc:
        raise InvalidArgumentError(
            f"Invalid search request: {exc}",
            {"filter": req.filter} if req.filter is not None else None,
        ) from exc
    except Exception as exc:
        raise ZvecOperationError(f"Failed to run search: {exc}") from exc

    results = [doc_mapper.from_zvec_doc(hit, include_vector=req.include_vector) for hit in hits]
    return SearchResponse(results=results)
