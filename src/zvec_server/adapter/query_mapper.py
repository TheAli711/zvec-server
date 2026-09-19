"""Translate our :class:`QuerySpec` models into native ``zvec.Query`` objects."""

from __future__ import annotations

from typing import Any

import zvec

from zvec_server.errors import InvalidArgumentError
from zvec_server.models.search import QuerySpec

__all__ = ["build_queries", "vector_index_types"]

_HNSW_PARAMS: dict[str, type] = {
    "ef": int,
    "radius": float,
    "is_linear": bool,
    "is_using_refiner": bool,
}

# Zvec index type name -> (query-param class, recognized API params and their types).
# Flat indexes take no query params.
_QUERY_PARAMS: dict[str, tuple[Any, dict[str, type]]] = {
    "HNSW": (zvec.HnswQueryParam, _HNSW_PARAMS),
    "HNSW_RABITQ": (zvec.HnswRabitqQueryParam, _HNSW_PARAMS),
    "IVF": (zvec.IVFQueryParam, {"nprobe": int}),
    "IVF_RABITQ": (
        zvec.IvfRabitqQueryParam,
        {
            "nprobe": int,
            "radius": float,
            "is_linear": bool,
            "is_using_refiner": bool,
            "scale_factor": float,
        },
    ),
}


def vector_index_types(collection: zvec.Collection) -> dict[str, str]:
    """Map each vector field of ``collection`` to its index type name (e.g. ``HNSW``)."""
    return {vec.name: vec.index_param.type.name for vec in collection.schema.vectors}


def _check_type(field: str, key: str, value: object, expected: type) -> Any:
    """Validate one query param value against its expected JSON type."""
    if expected is bool:
        ok = isinstance(value, bool)
    elif expected is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:  # float: accept any JSON number
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not ok:
        raise InvalidArgumentError(
            f"Query parameter {key!r} for field {field!r} must be {expected.__name__}",
            {"field": field, "param": key, "got": repr(value)},
        )
    return value


def _build_query_param(spec: QuerySpec, index_type: str | None) -> Any:
    """Translate ``spec.params`` into the query-param object for the field's index."""
    params = spec.params
    if not params:
        return None
    if index_type is None:
        raise InvalidArgumentError(f"Unknown vector field {spec.field!r}", {"field": spec.field})
    param_cls, allowed = _QUERY_PARAMS.get(index_type, (None, {}))
    unknown = sorted(set(params) - set(allowed))
    if unknown:
        raise InvalidArgumentError(
            f"Unknown query parameter(s) for {index_type.lower()} field "
            f"{spec.field!r}: {', '.join(unknown)}",
            {"field": spec.field, "unknown": unknown, "valid": sorted(allowed)},
        )
    kwargs = {
        key: _check_type(spec.field, key, value, allowed[key]) for key, value in params.items()
    }
    return param_cls(**kwargs)


def _build_query(spec: QuerySpec, index_types: dict[str, str]) -> zvec.Query:
    """Build a single ``zvec.Query`` from a query spec (vector or id)."""
    param = _build_query_param(spec, index_types.get(spec.field))
    if spec.vector is not None:
        return zvec.Query(field_name=spec.field, vector=spec.vector, param=param)
    return zvec.Query(field_name=spec.field, id=spec.id, param=param)


def build_queries(specs: list[QuerySpec], index_types: dict[str, str]) -> list[zvec.Query]:
    """Convert :class:`QuerySpec` models into native ``zvec.Query`` objects.

    Args:
        specs: The API query specs.
        index_types: Vector field name -> index type name, from
            :func:`vector_index_types`; selects which query params are valid.

    Raises:
        InvalidArgumentError: If a spec carries params its field's index doesn't
            support, or a param has the wrong type.
    """
    return [_build_query(spec, index_types) for spec in specs]
