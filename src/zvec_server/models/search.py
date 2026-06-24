"""Pydantic models for vector search requests and responses.

A search runs one or more nearest-neighbour queries against a collection,
optionally filtered by a SQL-like predicate. These models never import
:mod:`zvec`; the adapter translates them into native ``zvec.Query`` objects.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from zvec_server.models.vectors import DocOut

__all__ = ["QuerySpec", "SearchRequest", "SearchResponse"]


class QuerySpec(BaseModel):
    """A single nearest-neighbour query against one vector field.

    Provide **exactly one** of ``vector`` (search by an explicit query vector) or
    ``id`` (search by an existing document's stored vector).
    """

    field: str = Field(description="Vector field to search against.")
    vector: list[float] | None = Field(default=None, description="Explicit query vector.")
    id: str | None = Field(
        default=None, description="Existing document id whose stored vector is the query."
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description='Index-specific query tuning, e.g. ``{"ef": 128}`` for HNSW.',
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> QuerySpec:
        """Require exactly one of ``vector`` / ``id``."""
        has_vector = self.vector is not None
        has_id = self.id is not None
        if has_vector == has_id:
            raise ValueError("provide exactly one of 'vector' or 'id'")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"field": "embedding", "vector": [0.12, 0.98, 0.05], "params": {"ef": 128}},
                {"field": "embedding", "id": "doc-1"},
            ]
        },
    }


class SearchRequest(BaseModel):
    """Body for the search endpoint."""

    queries: list[QuerySpec] = Field(min_length=1, description="One or more queries to execute.")
    topk: int = Field(default=10, ge=1, le=1000, description="Maximum hits to return per query.")
    filter: str | None = Field(
        default=None,
        description=(
            "SQL-like predicate restricting candidates, e.g. "
            "``category = 'tech' AND year > 2020``. Passed through to Zvec verbatim."
        ),
    )
    include_vector: bool = Field(
        default=False, description="Whether to include vectors in the hits."
    )
    output_fields: list[str] | None = Field(
        default=None, description="Restrict returned scalar fields. None returns all."
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "queries": [{"field": "embedding", "vector": [0.12, 0.98, 0.05]}],
                    "topk": 10,
                    "filter": "category = 'tech'",
                    "include_vector": False,
                    "output_fields": ["category", "year"],
                }
            ]
        },
    }


class SearchResponse(BaseModel):
    """Search results as a flat list of hits sorted by score."""

    results: list[DocOut] = Field(description="Matching documents, best first.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "results": [
                        {
                            "id": "doc-1",
                            "score": 0.0123,
                            "fields": {"category": "tech", "year": 2024},
                        }
                    ]
                }
            ]
        },
    }
