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


def _build_vector_index_param(spec: VectorFieldSpec) -> Any:
    """Construct the right Zvec index-param object for a vector field."""
    index = enums.validate_index_type(spec.index)
    metric = enums.parse_metric_type(spec.metric)
    params = spec.params or {}

    if index == "hnsw":
        kwargs: dict[str, Any] = {"metric_type": metric}
        m = _int_param(params, "m")
        if m is not None:
            kwargs["m"] = m
        ef_construction = _int_param(params, "ef_construction")
        if ef_construction is not None:
            kwargs["ef_construction"] = ef_construction
        return zvec.HnswIndexParam(**kwargs)

    if index == "ivf":
        kwargs = {"metric_type": metric}
        n_list = _int_param(params, "n_list")
        if n_list is not None:
            kwargs["n_list"] = n_list
        n_iters = _int_param(params, "n_iters")
        if n_iters is not None:
            kwargs["n_iters"] = n_iters
        return zvec.IVFIndexParam(**kwargs)

    # flat: no tuning parameters beyond the metric.
    return zvec.FlatIndexParam(metric_type=metric)


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
