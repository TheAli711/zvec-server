"""Low-level collection lifecycle helpers over the Zvec engine.

These wrap the raw ``zvec`` create/open/close/destroy/flush/optimize/stats calls and
translate engine failures into our error hierarchy. They contain no locking or
threadpool offload; that is the manager's responsibility.
"""

from __future__ import annotations

import zvec

from zvec_server.errors import (
    CollectionAlreadyExistsError,
    SchemaValidationError,
    ZvecOperationError,
    ZvecServerError,
)
from zvec_server.models.collections import CollectionStats

__all__ = [
    "close_collection",
    "create_collection",
    "destroy_collection",
    "flush_collection",
    "get_stats",
    "open_collection",
    "optimize_collection",
    "schema_to_dicts",
]


def create_collection(
    path: str,
    schema: zvec.CollectionSchema,
    enable_mmap: bool,
) -> zvec.Collection:
    """Create and open a new collection on disk.

    Args:
        path: Directory for the collection's data.
        schema: The native collection schema.
        enable_mmap: Whether to memory-map the collection's storage.

    Raises:
        CollectionAlreadyExistsError: If a collection already exists at ``path``.
        SchemaValidationError: If the engine rejects the schema, or the index type
            is unsupported on this platform.
        ZvecOperationError: For any other engine failure.
    """
    option = zvec.CollectionOption(enable_mmap=enable_mmap, read_only=False)
    try:
        return zvec.create_and_open(path, schema, option)
    except ZvecServerError:
        raise
    except ValueError as exc:
        # Zvec raises ValueError both for an existing path and for a schema it
        # rejects; only the former is a conflict.
        if "path validate failed" in str(exc):
            raise CollectionAlreadyExistsError(
                f"A collection already exists at {path!r}", {"path": path}
            ) from exc
        raise SchemaValidationError(f"Invalid collection schema: {exc}", {"path": path}) from exc
    except Exception as exc:
        # e.g. "RabitQ is not supported on this platform (Linux x86_64 only)".
        if isinstance(exc, RuntimeError) and "not supported on this platform" in str(exc):
            raise SchemaValidationError(str(exc), {"path": path}) from exc
        raise ZvecOperationError(f"Failed to create collection: {exc}", {"path": path}) from exc


def open_collection(path: str, enable_mmap: bool) -> zvec.Collection:
    """Open an existing collection on disk.

    Raises:
        ZvecOperationError: If the collection cannot be opened.
    """
    option = zvec.CollectionOption(enable_mmap=enable_mmap, read_only=False)
    try:
        return zvec.open(path, option)
    except ZvecServerError:
        raise
    except Exception as exc:
        raise ZvecOperationError(f"Failed to open collection: {exc}", {"path": path}) from exc


def close_collection(collection: zvec.Collection) -> None:
    """Release an open collection's file handles and on-disk lock.

    The handle is unusable afterwards; callers must drop every reference to it.

    Raises:
        ZvecOperationError: If the close fails.
    """
    try:
        collection.close()
    except ZvecServerError:
        raise
    except Exception as exc:
        raise ZvecOperationError(f"Failed to close collection: {exc}") from exc


def destroy_collection(collection: zvec.Collection) -> None:
    """Delete a collection from disk.

    Raises:
        ZvecOperationError: If the destroy operation fails.
    """
    try:
        collection.destroy()
    except ZvecServerError:
        raise
    except Exception as exc:
        raise ZvecOperationError(f"Failed to destroy collection: {exc}") from exc


def flush_collection(collection: zvec.Collection) -> None:
    """Persist any buffered writes to disk.

    Raises:
        ZvecOperationError: If the flush fails.
    """
    try:
        collection.flush()
    except ZvecServerError:
        raise
    except Exception as exc:
        raise ZvecOperationError(f"Failed to flush collection: {exc}") from exc


def optimize_collection(collection: zvec.Collection) -> None:
    """Run background index optimization (segment merge, index build).

    Raises:
        ZvecOperationError: If optimization fails.
    """
    try:
        collection.optimize(zvec.OptimizeOption())
    except ZvecServerError:
        raise
    except Exception as exc:
        raise ZvecOperationError(f"Failed to optimize collection: {exc}") from exc


def get_stats(collection: zvec.Collection) -> CollectionStats:
    """Read live document/index statistics from an open collection.

    Raises:
        ZvecOperationError: If stats cannot be read.
    """
    try:
        stats = collection.stats
        return CollectionStats(
            doc_count=int(stats.doc_count),
            index_completeness=dict(stats.index_completeness),
        )
    except ZvecServerError:
        raise
    except Exception as exc:
        raise ZvecOperationError(f"Failed to read collection stats: {exc}") from exc


def schema_to_dicts(
    schema: zvec.CollectionSchema,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Serialize a collection schema into JSON-able ``(vectors, fields)`` dicts.

    Uses each ``VectorSchema``/``FieldSchema``'s ``__dict__()`` method.
    """
    vectors = [vec.__dict__() for vec in schema.vectors]
    fields = [field.__dict__() for field in schema.fields]
    return vectors, fields
