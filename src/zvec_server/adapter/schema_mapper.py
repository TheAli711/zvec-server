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
# Product-quantization settings (only valid with ``quantize_type: "pq"``).
_PQ_PARAMS = frozenset({"num_chunk", "num_bits", "opq_iter", "opq_pq_iter"})
_IVF_PQ_PARAMS = _PQ_PARAMS | {"fast_scan"}

# Recognized ``params`` keys per index type. Anything else is rejected so a typo
# (e.g. ``quantize`` for ``quantize_type``) can't silently build a different index.
_INDEX_PARAMS: dict[str, frozenset[str]] = {
    "hnsw": frozenset({"m", "ef_construction"}) | _QUANTIZE_PARAMS | _PQ_PARAMS,
    "ivf": frozenset({"n_list", "n_iters", "use_soar"}) | _QUANTIZE_PARAMS | _IVF_PQ_PARAMS,
    "flat": _QUANTIZE_PARAMS,
    "hnsw_rabitq": frozenset(
        {"m", "ef_construction", "total_bits", "num_clusters", "sample_count"}
    ),
    "ivf_rabitq": frozenset({"n_list", "total_bits", "sample_count"}),
}

# API param name -> Zvec kwarg, where they differ (kept uniform across IVF kinds).
_KWARG_NAMES: dict[str, str] = {"ivf_rabitq.n_list": "nlist"}

# Quantize types each index accepts. Zvec rejects the others, but with less
# specific errors (or, for some combinations, a generic engine failure).
_INDEX_QUANTIZE_TYPES: dict[str, frozenset[str]] = {
    "hnsw": enums.QUANTIZE_TYPES,
    "ivf": enums.SCALAR_QUANTIZE_TYPES | {"pq"},
    "flat": enums.SCALAR_QUANTIZE_TYPES,
}

_PQ_NUM_BITS = (4, 8)
# OPQ training runs inside optimize (holding the maintenance mutex), and Zvec
# takes these as uint32, so keep them to a sane range. Defaults are 5 and 4.
_MAX_OPQ_ITERS = 100
_ROTATABLE_QUANTIZE_TYPES = frozenset({"int8", "int4", "pq"})


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


def _check_quantize_type(
    index: str, spec: VectorFieldSpec, metric: zvec.MetricType, quantize_type: str
) -> None:
    """Reject a quantize type the index, metric, or vector dtype can't use."""
    allowed = _INDEX_QUANTIZE_TYPES[index]
    if quantize_type not in allowed:
        raise SchemaValidationError(
            f"quantize_type {quantize_type!r} is not supported on {index!r} indexes",
            {"index": index, "valid": sorted(allowed)},
        )
    if quantize_type in enums.UNIFORM_QUANTIZE_TYPES and metric.name != "L2":
        raise SchemaValidationError(
            f"quantize_type {quantize_type!r} requires metric 'l2'",
            {"metric": spec.metric, "valid_metrics": ["l2"]},
        )
    if quantize_type == "pq" and spec.dtype.upper() != "VECTOR_FP32":
        raise SchemaValidationError(
            "quantize_type 'pq' requires dtype 'VECTOR_FP32'",
            {"dtype": spec.dtype},
        )


def _check_rotation(index: str, quantize_type: str) -> None:
    """Reject ``enable_rotate: true`` where it fails or returns wrong results."""
    # Zvec only rotates int8/int4 (and learns OPQ for pq). With fp16 it accepts the
    # schema but every insert fails; with a uniform quantizer the create fails.
    if quantize_type not in _ROTATABLE_QUANTIZE_TYPES:
        raise SchemaValidationError(
            f"enable_rotate is not supported with {quantize_type!r} quantization; "
            "it requires quantize_type 'int8', 'int4', or 'pq'",
            {"quantize_type": quantize_type, "valid": sorted(_ROTATABLE_QUANTIZE_TYPES)},
        )
    # Zvec 0.8.0/0.8.1 regression: a new HNSW index with int8/int4 quantization and
    # rotation returns near-random results after optimize (ZS-069, alibaba/zvec#886).
    # Flat/IVF and PQ + OPQ are unaffected. Remove this when the canary in
    # tests/unit/test_upstream_regressions.py starts passing (ZS-076).
    if index == "hnsw" and quantize_type in ("int8", "int4"):
        raise SchemaValidationError(
            f"enable_rotate is not supported on hnsw indexes with {quantize_type} "
            "quantization: Zvec 0.8 returns wrong results for this combination "
            "after optimize (alibaba/zvec#886). Use a flat or ivf index, or omit "
            "enable_rotate.",
            {"index": index, "quantize_type": quantize_type},
        )


def _pq_kwargs(spec: VectorFieldSpec, params: dict[str, Any], rotate: bool) -> dict[str, Any]:
    """Validate the PQ settings and return them as ``zvec.QuantizerParam`` kwargs.

    Zvec reports every bad PQ value with the same generic message (and an
    out-of-range iteration count crashes its constructor), so the ranges are
    checked here.
    """
    kwargs: dict[str, Any] = {}
    num_chunk = _int_param(params, "num_chunk")
    # Zvec's default chunk count still has to fit the dimension.
    effective_chunks = num_chunk if num_chunk is not None else zvec.QuantizerParam().num_chunk
    if not 1 <= effective_chunks <= spec.dim:
        raise SchemaValidationError(
            f"Index parameter 'num_chunk' must be between 1 and the vector dimension "
            f"({spec.dim}); got {effective_chunks}"
            + ("" if num_chunk is not None else " (the default)"),
            {"num_chunk": effective_chunks, "dim": spec.dim},
        )
    if num_chunk is not None:
        kwargs["num_chunk"] = num_chunk

    num_bits = _int_param(params, "num_bits")
    if num_bits is not None:
        if num_bits not in _PQ_NUM_BITS:
            raise SchemaValidationError(
                "Index parameter 'num_bits' must be 4 or 8",
                {"got": num_bits, "valid": list(_PQ_NUM_BITS)},
            )
        kwargs["num_bits"] = num_bits

    fast_scan = _bool_param(params, "fast_scan")
    if fast_scan is not None:
        if fast_scan and num_bits != 4:
            raise SchemaValidationError(
                "Index parameter 'fast_scan' requires 'num_bits': 4",
                {"num_bits": num_bits},
            )
        if fast_scan and spec.dim % effective_chunks:
            raise SchemaValidationError(
                f"Index parameter 'fast_scan' requires 'num_chunk' to divide the vector "
                f"dimension ({spec.dim}); got {effective_chunks}"
                + ("" if num_chunk is not None else " (the default)"),
                {"num_chunk": effective_chunks, "dim": spec.dim},
            )
        kwargs["fast_scan"] = fast_scan

    for key in ("opq_iter", "opq_pq_iter"):
        value = _int_param(params, key)
        if value is None:
            continue
        if not rotate:
            raise SchemaValidationError(
                f"Index parameter {key!r} requires 'enable_rotate': true (OPQ)",
                {"param": key},
            )
        if not 1 <= value <= _MAX_OPQ_ITERS:
            raise SchemaValidationError(
                f"Index parameter {key!r} must be between 1 and {_MAX_OPQ_ITERS}",
                {"got": value},
            )
        kwargs[key] = value
    return kwargs


def _quantize_kwargs(
    index: str, spec: VectorFieldSpec, metric: zvec.MetricType, params: dict[str, Any]
) -> dict[str, Any]:
    """Translate the quantization ``params`` into index-param kwargs.

    ``enable_rotate`` applies a random rotation before ``int8``/``int4``
    quantization, or learns an OPQ rotation for ``pq``. Whether it helps recall is
    data-dependent (it hurt ``int4`` on SIFT1M), so it is off unless requested.
    """
    kwargs: dict[str, Any] = {}
    quantize_type: str | None = None
    if "quantize_type" in params:
        kwargs["quantize_type"] = enums.parse_quantize_type(params["quantize_type"])
        quantize_type = str(params["quantize_type"]).lower()
        _check_quantize_type(index, spec, metric, quantize_type)

    enable_rotate = _bool_param(params, "enable_rotate")
    if enable_rotate is not None and quantize_type is None:
        raise SchemaValidationError(
            "Index parameter 'enable_rotate' requires 'quantize_type'",
            {"params": sorted(params)},
        )
    if enable_rotate and quantize_type is not None:
        _check_rotation(index, quantize_type)

    pq_keys = sorted(k for k in _IVF_PQ_PARAMS if k in params)
    if pq_keys and quantize_type != "pq":
        raise SchemaValidationError(
            f"Index parameter(s) {', '.join(pq_keys)} require 'quantize_type': 'pq'",
            {"params": pq_keys},
        )
    pq = _pq_kwargs(spec, params, bool(enable_rotate)) if quantize_type == "pq" else {}

    if enable_rotate is not None or pq:
        kwargs["quantizer_param"] = zvec.QuantizerParam(enable_rotate=bool(enable_rotate), **pq)
    return kwargs


def _build_vector_index_param(spec: VectorFieldSpec) -> Any:
    """Construct the right Zvec index-param object for a vector field."""
    index = enums.validate_index_type(spec.index)
    metric = enums.parse_metric_type(spec.metric)
    params = spec.params or {}
    _check_param_keys(index, params)

    if index == "hnsw":
        kwargs: dict[str, Any] = {
            "metric_type": metric,
            **_quantize_kwargs(index, spec, metric, params),
        }
        m = _int_param(params, "m")
        if m is not None:
            kwargs["m"] = m
        ef_construction = _int_param(params, "ef_construction")
        if ef_construction is not None:
            kwargs["ef_construction"] = ef_construction
        return zvec.HnswIndexParam(**kwargs)

    if index == "ivf":
        kwargs = {"metric_type": metric, **_quantize_kwargs(index, spec, metric, params)}
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

    if index in ("hnsw_rabitq", "ivf_rabitq"):
        # RaBitQ indexes quantize by construction; every param is an int.
        kwargs = {"metric_type": metric}
        for key in sorted(params):
            value = _int_param(params, key)
            kwargs[_KWARG_NAMES.get(f"{index}.{key}", key)] = value
        if index == "hnsw_rabitq":
            return zvec.HnswRabitqIndexParam(**kwargs)
        return zvec.IvfRabitqIndexParam(**kwargs)

    # flat: no tuning parameters beyond the metric and quantization.
    return zvec.FlatIndexParam(metric_type=metric, **_quantize_kwargs(index, spec, metric, params))


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
