"""Translate our :class:`QuerySpec` models into native ``zvec.Query`` objects."""

from __future__ import annotations

import math
from typing import Any, NamedTuple

import zvec

from zvec_server.errors import InvalidArgumentError
from zvec_server.models.search import QuerySpec

__all__ = ["VectorIndexInfo", "build_queries", "vector_index_info"]

# Zvec sizes the refine candidate buffer as scale_factor x topk in an int32;
# beyond ~2**31 the query fails inside the engine.
_MAX_SCALE_FACTOR = 1000.0

_HNSW_PARAMS: dict[str, type] = {
    "ef": int,
    "radius": float,
    "is_linear": bool,
    "is_using_refiner": bool,
    "scale_factor": float,
}

# Zvec index type name -> (query-param class, recognized API params and their types).
# Flat indexes take no query params.
_QUERY_PARAMS: dict[str, tuple[Any, dict[str, type]]] = {
    "HNSW": (zvec.HnswQueryParam, _HNSW_PARAMS),
    "HNSW_RABITQ": (zvec.HnswRabitqQueryParam, _HNSW_PARAMS),
    "IVF": (
        zvec.IVFQueryParam,
        {"nprobe": int, "is_using_refiner": bool, "scale_factor": float},
    ),
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


class VectorIndexInfo(NamedTuple):
    """How a vector field is indexed, read from the open collection's schema."""

    index_type: str
    """Zvec index type name, e.g. ``HNSW``."""
    quantize_type: str
    """Zvec quantize type name, e.g. ``INT8``; ``UNDEFINED`` when unquantized."""


def vector_index_info(collection: zvec.Collection) -> dict[str, VectorIndexInfo]:
    """Map each vector field of ``collection`` to its index and quantize type."""
    info: dict[str, VectorIndexInfo] = {}
    for vec in collection.schema.vectors:
        param = vec.index_param
        quantize = getattr(param, "quantize_type", None)
        info[vec.name] = VectorIndexInfo(
            param.type.name, quantize.name if quantize is not None else "UNDEFINED"
        )
    return info


def _check_type(field: str, key: str, value: object, expected: type) -> Any:
    """Validate one query param value against its expected JSON type."""
    if expected is bool:
        ok = isinstance(value, bool)
    elif expected is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:  # float: any finite JSON number (the parser also accepts NaN/Infinity)
        ok = (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    if not ok:
        raise InvalidArgumentError(
            f"Query parameter {key!r} for field {field!r} must be {expected.__name__}",
            {"field": field, "param": key, "got": repr(value)},
        )
    return value


def _check_refiner(field: str, info: VectorIndexInfo, kwargs: dict[str, Any]) -> None:
    """Reject refiner settings the engine can't execute (it fails with a 500)."""
    scale_factor = kwargs.get("scale_factor")
    if scale_factor is not None and not 0 <= scale_factor <= _MAX_SCALE_FACTOR:
        raise InvalidArgumentError(
            f"Query parameter 'scale_factor' for field {field!r} must be between 0 "
            f"and {_MAX_SCALE_FACTOR:g}",
            {"field": field, "param": "scale_factor", "got": scale_factor},
        )
    # An unquantized HNSW index has nothing to refine; Zvec errors after optimize.
    if kwargs.get("is_using_refiner") and info == VectorIndexInfo("HNSW", "UNDEFINED"):
        raise InvalidArgumentError(
            f"Query parameter 'is_using_refiner' requires a quantized index; "
            f"hnsw field {field!r} has no quantize_type",
            {"field": field, "param": "is_using_refiner"},
        )


def _build_query_param(spec: QuerySpec, info: VectorIndexInfo | None) -> Any:
    """Translate ``spec.params`` into the query-param object for the field's index."""
    params = spec.params
    if not params:
        return None
    if info is None:
        raise InvalidArgumentError(f"Unknown vector field {spec.field!r}", {"field": spec.field})
    param_cls, allowed = _QUERY_PARAMS.get(info.index_type, (None, {}))
    unknown = sorted(set(params) - set(allowed))
    if unknown:
        raise InvalidArgumentError(
            f"Unknown query parameter(s) for {info.index_type.lower()} field "
            f"{spec.field!r}: {', '.join(unknown)}",
            {"field": spec.field, "unknown": unknown, "valid": sorted(allowed)},
        )
    kwargs = {
        key: _check_type(spec.field, key, value, allowed[key]) for key, value in params.items()
    }
    _check_refiner(spec.field, info, kwargs)
    return param_cls(**kwargs)


def _build_query(spec: QuerySpec, index_info: dict[str, VectorIndexInfo]) -> zvec.Query:
    """Build a single ``zvec.Query`` from a query spec (vector or id)."""
    param = _build_query_param(spec, index_info.get(spec.field))
    if spec.vector is not None:
        return zvec.Query(field_name=spec.field, vector=spec.vector, param=param)
    return zvec.Query(field_name=spec.field, id=spec.id, param=param)


def build_queries(
    specs: list[QuerySpec], index_info: dict[str, VectorIndexInfo]
) -> list[zvec.Query]:
    """Convert :class:`QuerySpec` models into native ``zvec.Query`` objects.

    Args:
        specs: The API query specs.
        index_info: Vector field name -> index info, from :func:`vector_index_info`;
            selects which query params are valid.

    Raises:
        InvalidArgumentError: If a spec carries params its field's index doesn't
            support, a param has the wrong type, or a refiner setting can't apply.
    """
    return [_build_query(spec, index_info) for spec in specs]
