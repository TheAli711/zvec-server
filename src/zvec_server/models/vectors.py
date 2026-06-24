"""Pydantic models for document-level operations: insert/upsert/update, delete,
and fetch.

A *document* is a primary key plus one or more named vectors and an optional set
of scalar fields. These models never import :mod:`zvec`; the adapter translates
between them and native ``zvec.Doc`` objects.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "DeleteRequest",
    "DeleteResponse",
    "DocIn",
    "DocOut",
    "FetchRequest",
    "FetchResponse",
    "WriteRequest",
    "WriteResponse",
    "WriteResultItem",
]


class DocIn(BaseModel):
    """An inbound document for insert/upsert/update.

    If ``id`` is omitted the server assigns a random UUID (hex) and returns it in
    the write response so the caller can reference the document later.
    """

    id: str | None = Field(
        default=None,
        description="Document primary key. If omitted, the server generates a UUID.",
    )
    vectors: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Mapping of vector-field name to its float vector.",
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Mapping of scalar-field name to value.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "doc-1",
                    "vectors": {"embedding": [0.12, 0.98, 0.05]},
                    "fields": {"category": "tech", "year": 2024},
                }
            ]
        },
    }


class DocOut(BaseModel):
    """A document returned from fetch or search.

    ``score`` is populated for search hits; ``vectors`` is included only when the
    caller requested it. ``fields`` is omitted when no scalar fields were returned.
    """

    id: str = Field(description="Document primary key.")
    score: float | None = Field(
        default=None, description="Similarity score for search results (omitted for fetches)."
    )
    vectors: dict[str, list[float]] | None = Field(
        default=None, description="Vectors, included only when requested."
    )
    fields: dict[str, Any] | None = Field(default=None, description="Scalar fields, when present.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "doc-1",
                    "score": 0.0123,
                    "vectors": {"embedding": [0.12, 0.98, 0.05]},
                    "fields": {"category": "tech", "year": 2024},
                }
            ]
        },
    }


class WriteRequest(BaseModel):
    """Body for the insert, upsert, and update endpoints."""

    docs: list[DocIn] = Field(min_length=1, description="One or more documents to write.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "docs": [
                        {
                            "id": "doc-1",
                            "vectors": {"embedding": [0.12, 0.98, 0.05]},
                            "fields": {"category": "tech"},
                        }
                    ]
                }
            ]
        },
    }


class WriteResultItem(BaseModel):
    """Per-document outcome of a write operation."""

    id: str | None = Field(
        default=None, description="Resolved document id (including server-generated ids)."
    )
    ok: bool = Field(description="Whether this document was written successfully.")
    code: str = Field(description="Engine status code name, e.g. ``OK`` or ``INVALID_ARGUMENT``.")
    message: str = Field(default="", description="Engine status message, if any.")

    model_config = {
        "json_schema_extra": {"examples": [{"id": "doc-1", "ok": True, "code": "OK"}]},
    }


class WriteResponse(BaseModel):
    """Aggregate result of a write operation across all documents."""

    results: list[WriteResultItem] = Field(description="Per-document results, in input order.")
    success_count: int = Field(description="Number of documents written successfully.")
    error_count: int = Field(description="Number of documents that failed.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "results": [{"id": "doc-1", "ok": True, "code": "OK", "message": ""}],
                    "success_count": 1,
                    "error_count": 0,
                }
            ]
        },
    }


class DeleteRequest(BaseModel):
    """Body for the delete endpoint.

    Specify **exactly one** of ``ids`` (delete specific documents) or ``filter``
    (delete everything matching a SQL-like predicate).
    """

    ids: list[str] | None = Field(default=None, description="Document ids to delete.")
    filter: str | None = Field(
        default=None,
        description=(
            "SQL-like predicate selecting documents to delete, e.g. "
            "``category = 'tech' AND year > 2020``. Passed through to Zvec verbatim."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> DeleteRequest:
        """Require exactly one of ``ids`` / ``filter``."""
        has_ids = self.ids is not None
        has_filter = self.filter is not None
        if has_ids == has_filter:
            raise ValueError("provide exactly one of 'ids' or 'filter'")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"ids": ["doc-1", "doc-2"]},
                {"filter": "category = 'tech' AND year > 2020"},
            ]
        },
    }


class DeleteResponse(BaseModel):
    """Result of a delete operation.

    For id-based deletes, ``results`` holds the per-id status. For filter-based
    deletes the engine reports no per-document status, so only ``ok`` and the
    echoed ``filter`` are returned.
    """

    ok: bool = Field(description="Whether the delete completed without error.")
    results: list[WriteResultItem] | None = Field(
        default=None, description="Per-id results (id-based deletes only)."
    )
    filter: str | None = Field(
        default=None, description="Echoed filter (filter-based deletes only)."
    )
    message: str | None = Field(default=None, description="Optional human-readable note.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ok": True,
                    "results": [{"id": "doc-1", "ok": True, "code": "OK", "message": ""}],
                },
                {"ok": True, "filter": "year < 2000", "message": "Deleted by filter."},
            ]
        },
    }


class FetchRequest(BaseModel):
    """Body for fetching documents by id."""

    ids: list[str] = Field(min_length=1, description="Document ids to fetch.")
    output_fields: list[str] | None = Field(
        default=None,
        description="Restrict returned scalar fields. None returns all fields.",
    )
    include_vector: bool = Field(
        default=False, description="Whether to include vectors in the response."
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"ids": ["doc-1", "doc-2"], "include_vector": False, "output_fields": ["category"]}
            ]
        },
    }


class FetchResponse(BaseModel):
    """Result of a fetch, keyed by document id (missing ids are omitted)."""

    docs: dict[str, DocOut] = Field(description="Found documents, keyed by id.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "docs": {
                        "doc-1": {"id": "doc-1", "fields": {"category": "tech"}},
                    }
                }
            ]
        },
    }
