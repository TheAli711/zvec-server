"""Translate between our document models and native ``zvec.Doc`` objects, and
map engine statuses back into API result models.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import zvec

from zvec_server.models.vectors import (
    DocIn,
    DocOut,
    WriteResponse,
    WriteResultItem,
)

__all__ = [
    "build_write_response",
    "from_zvec_doc",
    "status_to_item",
    "to_zvec_doc",
    "to_zvec_docs",
]


def to_zvec_doc(doc: DocIn) -> zvec.Doc:
    """Convert an inbound :class:`DocIn` into a ``zvec.Doc``.

    If the document has no id, a random ``uuid4().hex`` is generated. The
    resolved id is reflected on the returned ``zvec.Doc``.
    """
    doc_id = doc.id if doc.id is not None else uuid4().hex
    return zvec.Doc(id=doc_id, vectors=dict(doc.vectors), fields=dict(doc.fields))


def to_zvec_docs(docs: list[DocIn]) -> tuple[list[zvec.Doc], list[str]]:
    """Convert a list of :class:`DocIn` into ``zvec.Doc`` objects.

    Returns:
        A tuple of ``(zvec_docs, resolved_ids)`` where ``resolved_ids`` includes
        any server-generated ids, in input order.
    """
    zvec_docs: list[zvec.Doc] = []
    resolved_ids: list[str] = []
    for doc in docs:
        zdoc = to_zvec_doc(doc)
        zvec_docs.append(zdoc)
        resolved_ids.append(zdoc.id)
    return zvec_docs, resolved_ids


def _to_float_list(vec: Any) -> list[float]:
    """Coerce a native vector value (list / numpy array) into ``list[float]``."""
    return [float(x) for x in vec]


def from_zvec_doc(doc: zvec.Doc, include_vector: bool) -> DocOut:
    """Convert a native ``zvec.Doc`` (fetch/search hit) into a :class:`DocOut`.

    Args:
        doc: The native document.
        include_vector: Whether to carry the vectors into the output.
    """
    fields: dict[str, Any] | None = dict(doc.fields) if doc.fields else None
    vectors: dict[str, list[float]] | None = None
    if include_vector and doc.vectors:
        vectors = {name: _to_float_list(vec) for name, vec in doc.vectors.items()}
    return DocOut(id=doc.id, score=doc.score, vectors=vectors, fields=fields)


def status_to_item(doc_id: str | None, status: Any) -> WriteResultItem:
    """Map a Zvec ``Status`` into a :class:`WriteResultItem`."""
    return WriteResultItem(
        id=doc_id,
        ok=status.ok(),
        code=status.code().name,
        message=status.message(),
    )


def build_write_response(ids: list[str], statuses: list[Any]) -> WriteResponse:
    """Assemble a :class:`WriteResponse` from resolved ids and engine statuses.

    Args:
        ids: Resolved document ids, in the same order as ``statuses``.
        statuses: Engine ``Status`` objects from insert/upsert/update.
    """
    results = [
        status_to_item(doc_id, status) for doc_id, status in zip(ids, statuses, strict=False)
    ]
    success_count = sum(1 for item in results if item.ok)
    error_count = len(results) - success_count
    return WriteResponse(
        results=results,
        success_count=success_count,
        error_count=error_count,
    )
