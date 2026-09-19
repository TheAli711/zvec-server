"""Translate our :class:`VectorFieldSpec`/:class:`ScalarFieldSpec` models into a
native ``zvec.CollectionSchema``.

This is the only place that turns API-level field specifications into Zvec index
parameters. Validation errors surface as :class:`SchemaValidationError`.
"""

from __future__ import annotations

from typing import Any

import zvec

from zvec_server.adapter import enums
from zvec_server.errors import SchemaValidationError
from zvec_server.models.collections import (
    CreateCollectionRequest,
    ScalarFieldSpec,
    VectorFieldSpec,
)

__all__ = ["build_collection_schema", "primary_vector_info"]


_QUANTIZE_PARAMS = frozenset({"quantize_type", "enable_rotate"})

# Recognized ``params`` keys per index type. Anything else is rejected so a typo
# (e.g. ``quantize`` for ``quantize_type``) can't silently build a different index.
_INDEX_PARAMS: dict[str, frozenset[str]] = {
    "hnsw": frozenset({"m", "ef_construction"}) | _QUANTIZE_PARAMS,
    "ivf": frozenset({"n_list", "n_iters", "use_soar"}) | _QUANTIZE_PARAMS,
    "flat": _QUANTIZE_PARAMS,
}


def _check_param_keys(index: str, params: dict[str, Any]) -> None:
    """Reject ``params`` keys the index type does not recognize."""
    unknown = sorted(set(params) - _INDEX_PARAMS[index])
    if unknown:
        raise SchemaValidationError(
            f"Unknown parameter(s) for {index!r} index: {', '.join(unknown)}",
            {"unknown": unknown, "valid": sorted(_INDEX_PARAMS[index])},
        )


def _int_param(params: dict[str, Any], key: str) -> int | None:
    """Read an optional positive-ish int parameter, validating its type."""
    if key not in params:
        return None
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(
            f"Index parameter {key!r} must be an integer",
            {"got": repr(value)},
        )
    return value


def _bool_param(params: dict[str, Any], key: str) -> bool | None:
    """Read an optional boolean parameter, validating its type."""
    if key not in params:
        return None
    value = params[key]
    if not isinstance(value, bool):
        raise SchemaValidationError(
            f"Index parameter {key!r} must be a boolean",
            {"got": repr(value)},
        )
    return value


def _quantize_kwargs(params: dict[str, Any]) -> dict[str, Any]:
    """Translate ``quantize_type`` / ``enable_rotate`` into index-param kwargs.

    ``enable_rotate`` applies a random rotation before quantizing, which spreads
    variance across dimensions and improves recall (most visibly for ``int4``).
    """
    kwargs: dict[str, Any] = {}
    if "quantize_type" in params:
        kwargs["quantize_type"] = enums.parse_quantize_type(params["quantize_type"])
    enable_rotate = _bool_param(params, "enable_rotate")
    if enable_rotate is not None:
        if "quantize_type" not in kwargs:
            raise SchemaValidationError(
                "Index parameter 'enable_rotate' requires 'quantize_type'",
                {"params": sorted(params)},
            )
        kwargs["quantizer_param"] = zvec.QuantizerParam(enable_rotate=enable_rotate)
    return kwargs


def _build_vector_index_param(spec: VectorFieldSpec) -> Any:
    """Construct the right Zvec index-param object for a vector field."""
    index = enums.validate_index_type(spec.index)
    metric = enums.parse_metric_type(spec.metric)
    params = spec.params or {}
    _check_param_keys(index, params)

    if index == "hnsw":
        kwargs: dict[str, Any] = {"metric_type": metric, **_quantize_kwargs(params)}
        m = _int_param(params, "m")
        if m is not None:
            kwargs["m"] = m
        ef_construction = _int_param(params, "ef_construction")
        if ef_construction is not None:
            kwargs["ef_construction"] = ef_construction
        return zvec.HnswIndexParam(**kwargs)

    if index == "ivf":
        kwargs = {"metric_type": metric, **_quantize_kwargs(params)}
        n_list = _int_param(params, "n_list")
        if n_list is not None:
            kwargs["n_list"] = n_list
        n_iters = _int_param(params, "n_iters")
        if n_iters is not None:
            kwargs["n_iters"] = n_iters
        use_soar = _bool_param(params, "use_soar")
        if use_soar is not None:
            kwargs["use_soar"] = use_soar
        return zvec.IVFIndexParam(**kwargs)

    # flat: no tuning parameters beyond the metric and quantization.
    return zvec.FlatIndexParam(metric_type=metric, **_quantize_kwargs(params))


def _build_vector_schema(spec: VectorFieldSpec) -> zvec.VectorSchema:
    """Build a single ``zvec.VectorSchema`` from a vector field spec."""
    if not enums.is_vector_type(spec.dtype):
        raise SchemaValidationError(
            f"Field {spec.name!r}: {spec.dtype!r} is not a vector data type",
            {"valid": sorted(enums.VECTOR_DATA_TYPES)},
        )
    data_type = enums.parse_data_type(spec.dtype)
    return zvec.VectorSchema(
        name=spec.name,
        data_type=data_type,
        dimension=spec.dim,
        index_param=_build_vector_index_param(spec),
    )


def _build_field_schema(spec: ScalarFieldSpec) -> zvec.FieldSchema:
    """Build a single ``zvec.FieldSchema`` from a scalar field spec."""
    if not enums.is_scalar_type(spec.dtype):
        raise SchemaValidationError(
            f"Field {spec.name!r}: {spec.dtype!r} is not a scalar data type",
            {"valid": sorted(enums.SCALAR_DATA_TYPES)},
        )
    data_type = enums.parse_data_type(spec.dtype)
    index_param = zvec.InvertIndexParam() if spec.indexed else None
    return zvec.FieldSchema(
        name=spec.name,
        data_type=data_type,
        nullable=spec.nullable,
        index_param=index_param,
    )


def build_collection_schema(
    name: str,
    vectors: list[VectorFieldSpec],
    fields: list[ScalarFieldSpec],
) -> zvec.CollectionSchema:
    """Build a ``zvec.CollectionSchema`` from API field specifications.

    Args:
        name: Collection name.
        vectors: Vector field specs (at least one expected).
        fields: Scalar field specs (may be empty).

    Returns:
        A native ``zvec.CollectionSchema`` ready for ``create_and_open``.

    Raises:
        SchemaValidationError: If any dtype, metric, or index parameter is invalid.
    """
    vector_schemas = [_build_vector_schema(v) for v in vectors]
    field_schemas = [_build_field_schema(f) for f in fields]
    return zvec.CollectionSchema(
        name=name,
        fields=field_schemas,
        vectors=vector_schemas,
    )


def primary_vector_info(req: CreateCollectionRequest) -> tuple[str, int]:
    """Return the ``(name, dimension)`` of the request's primary (first) vector.

    Used to populate the denormalized columns in the metadata store.

    Raises:
        SchemaValidationError: If the request has no vector fields.
    """
    if not req.vectors:
        raise SchemaValidationError("Collection must define at least one vector field")
    primary = req.vectors[0]
    return primary.name, primary.dim
