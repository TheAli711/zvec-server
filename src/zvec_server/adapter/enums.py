"""Translation between API enum strings and Zvec's native enum types.

Keeping this in one place means the rest of the adapter (and the API models) can
speak in lowercase/uppercase strings while the SDK gets its real enum members.
"""

from __future__ import annotations

import zvec

from zvec_server.errors import SchemaValidationError

# Vector data types accepted on vector fields (see zvec SUPPORT_VECTOR_DATA_TYPE).
VECTOR_DATA_TYPES: frozenset[str] = frozenset(
    {
        "VECTOR_FP16",
        "VECTOR_FP32",
        "VECTOR_FP64",
        "VECTOR_INT8",
        "SPARSE_VECTOR_FP16",
        "SPARSE_VECTOR_FP32",
    }
)

# Scalar / array data types accepted on scalar fields (see zvec SUPPORT_SCALAR_DATA_TYPE).
SCALAR_DATA_TYPES: frozenset[str] = frozenset(
    {
        "INT32",
        "INT64",
        "UINT32",
        "UINT64",
        "FLOAT",
        "DOUBLE",
        "STRING",
        "BOOL",
        "ARRAY_INT32",
        "ARRAY_INT64",
        "ARRAY_UINT32",
        "ARRAY_UINT64",
        "ARRAY_FLOAT",
        "ARRAY_DOUBLE",
        "ARRAY_STRING",
        "ARRAY_BOOL",
    }
)

# Supported vector index kinds (lowercase API tokens).
INDEX_TYPES: frozenset[str] = frozenset({"hnsw", "flat", "ivf"})

# Convenience metric aliases accepted in addition to Zvec's own names.
_METRIC_ALIASES: dict[str, str] = {
    "DOT": "IP",
    "INNER_PRODUCT": "IP",
    "EUCLIDEAN": "L2",
}


def parse_data_type(name: str) -> zvec.DataType:
    """Resolve a data-type string (case-insensitive) to a ``zvec.DataType``."""
    key = (name or "").upper()
    member = zvec.DataType.__members__.get(key)
    if member is None:
        raise SchemaValidationError(
            f"Unknown data type {name!r}",
            {"valid": sorted(zvec.DataType.__members__)},
        )
    return member


def parse_metric_type(name: str) -> zvec.MetricType:
    """Resolve a metric string (case-insensitive, with aliases) to ``zvec.MetricType``."""
    key = (name or "").upper()
    key = _METRIC_ALIASES.get(key, key)
    member = zvec.MetricType.__members__.get(key)
    if member is None:
        raise SchemaValidationError(
            f"Unknown metric type {name!r}",
            {"valid": sorted(zvec.MetricType.__members__)},
        )
    return member


def validate_index_type(name: str) -> str:
    """Validate and normalize a vector index token (``hnsw`` / ``flat`` / ``ivf``)."""
    key = (name or "").lower()
    if key not in INDEX_TYPES:
        raise SchemaValidationError(
            f"Unknown vector index type {name!r}",
            {"valid": sorted(INDEX_TYPES)},
        )
    return key


def data_type_name(dtype: zvec.DataType) -> str:
    """Return the canonical string name for a ``zvec.DataType``."""
    return dtype.name


def metric_type_name(metric: zvec.MetricType) -> str:
    """Return the canonical string name for a ``zvec.MetricType``."""
    return metric.name


def is_vector_type(name: str) -> bool:
    return (name or "").upper() in VECTOR_DATA_TYPES


def is_scalar_type(name: str) -> bool:
    return (name or "").upper() in SCALAR_DATA_TYPES
