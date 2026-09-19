"""Pydantic models for vector search requests and responses.

A search runs one or more nearest-neighbour queries against a collection,
optionally filtered by a SQL-like predicate. These models never import
:mod:`zvec`; the adapter translates them into native ``zvec.Query`` objects.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from zvec_server.models.vectors import DocOut

__all__ = [
    "GroupOut",
    "GroupSearchRequest",
    "GroupSearchResponse",
    "QuerySpec",
    "SearchRequest",
    "SearchResponse",
]


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
        description=(
            "Index-specific query tuning. hnsw/hnsw_rabitq: ``ef``, ``radius``, "
            "``is_linear``, ``is_using_refiner``. ivf: ``nprobe``. ivf_rabitq: "
            "``nprobe``, ``radius``, ``is_linear``, ``is_using_refiner``, "
            "``scale_factor``. flat: none. Unknown keys are rejected."
        ),
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


class GroupSearchRequest(BaseModel):
    """Body for the group-by search endpoint.

    Runs one nearest-neighbour query, buckets hits by the value of a scalar
    field, and returns the best ``topk_per_group`` hits from each of the best
    ``group_count`` groups — e.g. the top chunks from each of the top documents.
    """

    query: QuerySpec = Field(description="The nearest-neighbour query to run.")
    group_by: str = Field(description="Scalar field whose value defines the groups.")
    group_count: int = Field(default=10, ge=1, le=1000, description="Maximum groups to return.")
    topk_per_group: int = Field(
        default=3, ge=1, le=1000, description="Maximum hits to return per group."
    )
    filter: str | None = Field(
        default=None,
        description="SQL-like predicate restricting candidates. Passed to Zvec verbatim.",
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
                    "query": {"field": "embedding", "vector": [0.12, 0.98, 0.05]},
                    "group_by": "doc_id",
                    "group_count": 5,
                    "topk_per_group": 2,
                }
            ]
        },
    }


class GroupOut(BaseModel):
    """One group of hits sharing a ``group_by`` value."""

    value: str = Field(
        description=(
            "The group's ``group_by`` value, always rendered as a string "
            '(a null value is returned as ``""``).'
        )
    )
    results: list[DocOut] = Field(description="The group's hits, best first.")


class GroupSearchResponse(BaseModel):
    """Group-by search results: groups ordered by their best hit."""

    groups: list[GroupOut] = Field(description="Matching groups, best first.")
