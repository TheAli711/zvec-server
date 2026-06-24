"""Pydantic models describing collections: their schema, creation requests, and
the metadata returned when listing or inspecting them.

These are pure data-transfer objects. They never import :mod:`zvec`; the adapter
layer is responsible for translating them into native Zvec schema objects.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "CollectionInfo",
    "CollectionListResponse",
    "CollectionOptions",
    "CollectionStats",
    "CollectionSummary",
    "CreateCollectionRequest",
    "ScalarFieldSpec",
    "VectorFieldSpec",
]

# Collection names map to on-disk directories, so keep them filesystem-safe.
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class VectorFieldSpec(BaseModel):
    """Definition of a single vector field within a collection.

    Each collection has one or more vector fields. The first one is treated as
    the *primary* vector for convenience metadata (e.g. ``embedding_dimension``).
    """

    name: str = Field(description="Vector field name, unique within the collection.")
    dim: int = Field(gt=0, description="Vector dimensionality (number of components).")
    dtype: str = Field(
        default="VECTOR_FP32",
        description=(
            "Vector storage type. One of ``VECTOR_FP16``/``VECTOR_FP32``/"
            "``VECTOR_FP64``/``VECTOR_INT8``/``SPARSE_VECTOR_FP16``/``SPARSE_VECTOR_FP32``."
        ),
    )
    index: str = Field(
        default="hnsw",
        description="Vector index type: ``hnsw``, ``flat``, or ``ivf``.",
    )
    metric: str = Field(
        default="cosine",
        description="Distance metric: ``cosine``, ``ip`` (inner product), or ``l2``.",
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Index-specific tuning parameters. HNSW: ``m``, ``ef_construction``. "
            "IVF: ``n_list``, ``n_iters``. Flat: none."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "embedding",
                    "dim": 768,
                    "dtype": "VECTOR_FP32",
                    "index": "hnsw",
                    "metric": "cosine",
                    "params": {"m": 16, "ef_construction": 200},
                }
            ]
        },
    }


class ScalarFieldSpec(BaseModel):
    """Definition of a scalar (non-vector) field stored alongside each document."""

    name: str = Field(description="Scalar field name, unique within the collection.")
    dtype: str = Field(
        description=(
            "Scalar storage type, e.g. ``STRING``, ``INT64``, ``DOUBLE``, ``BOOL``, "
            "or an ``ARRAY_*`` variant."
        ),
    )
    nullable: bool = Field(
        default=False,
        description="Whether documents may omit this field (store NULL).",
    )
    indexed: bool = Field(
        default=False,
        description="Whether to build an inverted index for filtering on this field.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"name": "category", "dtype": "STRING", "nullable": False, "indexed": True}
            ]
        },
    }


class CollectionOptions(BaseModel):
    """Optional per-collection storage tuning. Unset values fall back to server defaults."""

    enable_mmap: bool | None = Field(
        default=None,
        description="Override the server default for memory-mapped storage.",
    )

    model_config = {"json_schema_extra": {"examples": [{"enable_mmap": True}]}}


class CreateCollectionRequest(BaseModel):
    """Request body for creating a new collection."""

    name: str = Field(
        description="Collection name; matches ``^[A-Za-z0-9_-]{1,128}$``.",
    )
    vectors: list[VectorFieldSpec] = Field(
        min_length=1,
        description="One or more vector field definitions (at least one required).",
    )
    fields: list[ScalarFieldSpec] = Field(
        default_factory=list,
        description="Optional scalar field definitions.",
    )
    options: CollectionOptions | None = Field(
        default=None,
        description="Optional storage tuning for this collection.",
    )
    embedding_model: str | None = Field(
        default=None,
        description="Free-form label recording which model produced the vectors.",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Reject names that are not filesystem/URL-safe."""
        if not _NAME_PATTERN.match(value):
            raise ValueError(
                "name must match ^[A-Za-z0-9_-]{1,128}$ "
                "(letters, digits, underscore, hyphen; 1-128 chars)"
            )
        return value

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "articles",
                    "vectors": [
                        {
                            "name": "embedding",
                            "dim": 768,
                            "dtype": "VECTOR_FP32",
                            "index": "hnsw",
                            "metric": "cosine",
                            "params": {"m": 16, "ef_construction": 200},
                        }
                    ],
                    "fields": [
                        {"name": "category", "dtype": "STRING", "indexed": True},
                        {"name": "year", "dtype": "INT64", "indexed": True},
                    ],
                    "options": {"enable_mmap": True},
                    "embedding_model": "text-embedding-3-small",
                }
            ]
        },
    }


class CollectionStats(BaseModel):
    """Live statistics read directly from the open collection."""

    doc_count: int = Field(description="Number of documents currently stored.")
    index_completeness: dict[str, float] = Field(
        default_factory=dict,
        description="Per-vector-field index build progress, from 0.0 to 1.0.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"doc_count": 12000, "index_completeness": {"embedding": 1.0}}]
        },
    }


class CollectionInfo(BaseModel):
    """Full description of a collection: schema, options, metadata, and live stats."""

    name: str = Field(description="Collection name.")
    path: str = Field(description="On-disk path where the collection is stored.")
    schema_version: int = Field(description="Metadata schema version for this record.")
    embedding_dimension: int | None = Field(
        default=None, description="Dimensionality of the primary vector field, if any."
    )
    embedding_model: str | None = Field(
        default=None, description="Recorded embedding model label, if provided at creation."
    )
    vectors: list[dict[str, Any]] = Field(
        description="Serialized vector field schemas as returned by Zvec."
    )
    fields: list[dict[str, Any]] = Field(
        description="Serialized scalar field schemas as returned by Zvec."
    )
    options: dict[str, Any] = Field(description="Storage options in effect for the collection.")
    stats: CollectionStats | None = Field(
        default=None, description="Live document/index statistics, when the collection is open."
    )
    available: bool = Field(
        default=True,
        description="False when the collection is registered but could not be opened on disk.",
    )
    created_at: str = Field(description="ISO-8601 UTC creation timestamp.")
    updated_at: str = Field(description="ISO-8601 UTC last-update timestamp.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "articles",
                    "path": "/data/collections/articles",
                    "schema_version": 1,
                    "embedding_dimension": 768,
                    "embedding_model": "text-embedding-3-small",
                    "vectors": [
                        {"name": "embedding", "data_type": "VECTOR_FP32", "dimension": 768}
                    ],
                    "fields": [{"name": "category", "data_type": "STRING", "nullable": False}],
                    "options": {"enable_mmap": True},
                    "stats": {"doc_count": 12000, "index_completeness": {"embedding": 1.0}},
                    "available": True,
                    "created_at": "2026-06-23T10:00:00+00:00",
                    "updated_at": "2026-06-23T10:00:00+00:00",
                }
            ]
        },
    }


class CollectionSummary(BaseModel):
    """Compact collection entry used in list responses."""

    name: str = Field(description="Collection name.")
    embedding_dimension: int | None = Field(
        default=None, description="Dimensionality of the primary vector field, if any."
    )
    embedding_model: str | None = Field(
        default=None, description="Recorded embedding model label, if provided."
    )
    doc_count: int | None = Field(
        default=None,
        description="Document count, when cheaply available (None if collection unavailable).",
    )
    created_at: str = Field(description="ISO-8601 UTC creation timestamp.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "articles",
                    "embedding_dimension": 768,
                    "embedding_model": "text-embedding-3-small",
                    "doc_count": 12000,
                    "created_at": "2026-06-23T10:00:00+00:00",
                }
            ]
        },
    }


class CollectionListResponse(BaseModel):
    """Response body for ``GET /collections``."""

    collections: list[CollectionSummary] = Field(description="All registered collections.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "collections": [
                        {
                            "name": "articles",
                            "embedding_dimension": 768,
                            "embedding_model": "text-embedding-3-small",
                            "doc_count": 12000,
                            "created_at": "2026-06-23T10:00:00+00:00",
                        }
                    ]
                }
            ]
        },
    }
