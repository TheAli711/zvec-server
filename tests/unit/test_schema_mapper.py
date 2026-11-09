"""Unit tests for :mod:`zvec_server.adapter.schema_mapper`."""

from __future__ import annotations

from typing import Any

import pytest

from zvec_server.adapter import collections as col_adapter
from zvec_server.adapter import runtime, schema_mapper
from zvec_server.errors import SchemaValidationError
from zvec_server.models.collections import (
    CreateCollectionRequest,
    ScalarFieldSpec,
    VectorFieldSpec,
)

# Building a CollectionSchema touches the engine, so make sure it is initialized.
runtime.init_zvec()


def test_build_schema_basic_hnsw() -> None:
    schema = schema_mapper.build_collection_schema(
        "c",
        [VectorFieldSpec(name="emb", dim=8, dtype="VECTOR_FP32", index="hnsw", metric="cosine")],
        [ScalarFieldSpec(name="cat", dtype="STRING", indexed=True, nullable=True)],
    )
    assert [(v.name, v.dimension, v.data_type.name) for v in schema.vectors] == [
        ("emb", 8, "VECTOR_FP32")
    ]
    assert [(f.name, f.data_type.name, f.nullable) for f in schema.fields] == [
        ("cat", "STRING", True)
    ]


def test_build_schema_hnsw_params_applied() -> None:
    schema = schema_mapper.build_collection_schema(
        "c",
        [
            VectorFieldSpec(
                name="emb",
                dim=4,
                index="hnsw",
                metric="ip",
                params={"m": 32, "ef_construction": 321},
            )
        ],
        [],
    )
    vectors, _ = col_adapter.schema_to_dicts(schema)
    index = vectors[0]["index_param"]
    assert index["type"] == "HNSW"
    assert index["metric_type"] == "IP"
    assert index["m"] == 32
    assert index["ef_construction"] == 321


def test_build_schema_ivf_params_applied() -> None:
    schema = schema_mapper.build_collection_schema(
        "c",
        [
            VectorFieldSpec(
                name="emb",
                dim=4,
                index="ivf",
                metric="l2",
                params={"n_list": 16, "n_iters": 7, "use_soar": True},
            )
        ],
        [],
    )
    vectors, _ = col_adapter.schema_to_dicts(schema)
    index = vectors[0]["index_param"]
    assert index["type"] == "IVF"
    assert index["n_list"] == 16
    assert index["n_iters"] == 7
    assert index["use_soar"] is True


def test_build_schema_flat() -> None:
    schema = schema_mapper.build_collection_schema(
        "c", [VectorFieldSpec(name="emb", dim=4, index="flat", metric="cosine")], []
    )
    vectors, _ = col_adapter.schema_to_dicts(schema)
    # Flat index params serialize without a "type" key, but carry the metric and
    # notably none of the HNSW/IVF tuning fields.
    index = vectors[0]["index_param"]
    assert index["metric_type"] == "COSINE"
    assert "m" not in index and "n_list" not in index


def test_build_schema_rabitq_params_applied() -> None:
    schema = schema_mapper.build_collection_schema(
        "c",
        [
            VectorFieldSpec(
                name="a",
                dim=64,
                index="hnsw_rabitq",
                params={"m": 24, "total_bits": 5, "num_clusters": 8},
            ),
            VectorFieldSpec(
                name="b", dim=64, index="ivf_rabitq", params={"n_list": 32, "total_bits": 4}
            ),
        ],
        [],
    )
    vectors, _ = col_adapter.schema_to_dicts(schema)
    hnsw, ivf = (v["index_param"] for v in vectors)
    assert (hnsw["type"], hnsw["m"], hnsw["total_bits"], hnsw["num_clusters"]) == (
        "HNSW_RABITQ",
        24,
        5,
        8,
    )
    assert (ivf["type"], ivf["nlist"], ivf["total_bits"]) == ("IVF_RABITQ", 32, 4)


def _index_param(
    index: str, params: dict[str, object], *, metric: str = "cosine", dim: int = 8
) -> dict[str, Any]:
    schema = schema_mapper.build_collection_schema(
        "c",
        [VectorFieldSpec(name="emb", dim=dim, index=index, metric=metric, params=params)],
        [],
    )
    vectors, _ = col_adapter.schema_to_dicts(schema)
    return dict(vectors[0]["index_param"])


def _schema_error(
    index: str, params: dict[str, object], *, metric: str = "cosine", dim: int = 8, **kw: Any
) -> SchemaValidationError:
    with pytest.raises(SchemaValidationError) as excinfo:
        schema_mapper.build_collection_schema(
            "c",
            [VectorFieldSpec(name="emb", dim=dim, index=index, metric=metric, params=params, **kw)],
            [],
        )
    return excinfo.value


@pytest.mark.parametrize("index", ["hnsw", "flat", "ivf"])
@pytest.mark.parametrize("quantize", ["fp16", "int8", "INT4"])
def test_build_schema_quantization(index: str, quantize: str) -> None:
    index_param = _index_param(index, {"quantize_type": quantize})
    assert index_param["quantize_type"] == quantize.upper()


@pytest.mark.parametrize("index", ["flat", "ivf"])
@pytest.mark.parametrize("quantize", ["int8", "int4"])
def test_build_schema_quantization_with_rotation(index: str, quantize: str) -> None:
    index_param = _index_param(index, {"quantize_type": quantize, "enable_rotate": True})
    assert index_param["quantize_type"] == quantize.upper()
    assert index_param["quantizer_param"]["enable_rotate"] is True


@pytest.mark.parametrize("index", ["hnsw", "flat", "ivf"])
def test_fp16_rotation_rejected(index: str) -> None:
    """ZS-077: Zvec accepts the schema but every insert then fails."""
    err = _schema_error(index, {"quantize_type": "fp16", "enable_rotate": True})
    assert "requires quantize_type 'int8', 'int4', or 'pq'" in err.message


@pytest.mark.parametrize("quantize", ["int8", "int4"])
def test_hnsw_scalar_rotation_rejected(quantize: str) -> None:
    """Zvec 0.8 regression guard (ZS-069): wrong results after optimize."""
    err = _schema_error("hnsw", {"quantize_type": quantize, "enable_rotate": True})
    assert "Zvec 0.8 returns wrong results" in err.message
    assert err.details == {"index": "hnsw", "quantize_type": quantize}
    # Explicitly off stays a harmless no-op.
    assert _index_param("hnsw", {"quantize_type": quantize, "enable_rotate": False})


@pytest.mark.parametrize("quantize", ["uniform_uint4", "uniform_uint7", "UNIFORM_UINT8"])
def test_build_schema_uniform_quantization(quantize: str) -> None:
    index_param = _index_param("hnsw", {"quantize_type": quantize}, metric="l2")
    assert index_param["quantize_type"] == quantize.upper()


@pytest.mark.parametrize(
    ("index", "metric", "match"),
    [
        ("ivf", "l2", "not supported on 'ivf'"),
        ("flat", "l2", "not supported on 'flat'"),
        ("hnsw", "cosine", "requires metric 'l2'"),
        ("hnsw", "ip", "requires metric 'l2'"),
    ],
)
def test_uniform_quantization_restrictions(index: str, metric: str, match: str) -> None:
    err = _schema_error(index, {"quantize_type": "uniform_uint8"}, metric=metric)
    assert match in err.message


def test_uniform_quantization_rejects_rotation() -> None:
    err = _schema_error(
        "hnsw", {"quantize_type": "uniform_uint8", "enable_rotate": True}, metric="l2"
    )
    assert "not supported with 'uniform_uint8'" in err.message


def test_build_schema_pq_defaults_and_settings() -> None:
    defaults = _index_param("hnsw", {"quantize_type": "pq"})
    assert defaults["quantize_type"] == "PQ"

    hnsw = _index_param(
        "hnsw",
        {
            "quantize_type": "pq",
            "num_chunk": 4,
            "num_bits": 4,
            "enable_rotate": True,
            "opq_iter": 2,
            "opq_pq_iter": 3,
        },
    )
    assert hnsw["quantizer_param"] == {
        "enable_rotate": True,
        "num_chunk": 4,
        "num_bits": 4,
        "fast_scan": False,
        "opq_iter": 2,
        "opq_pq_iter": 3,
    }

    ivf = _index_param(
        "ivf", {"quantize_type": "pq", "num_chunk": 8, "num_bits": 4, "fast_scan": True}
    )
    assert (ivf["quantize_type"], ivf["quantizer_param"]["fast_scan"]) == ("PQ", True)


@pytest.mark.parametrize(
    ("index", "params", "match"),
    [
        ("flat", {"quantize_type": "pq"}, "not supported on 'flat'"),
        ("hnsw", {"quantize_type": "int8", "num_chunk": 4}, "require 'quantize_type': 'pq'"),
        ("ivf", {"fast_scan": True}, "require 'quantize_type': 'pq'"),
        ("hnsw", {"quantize_type": "pq", "num_chunk": 0}, "between 1 and the vector dimension"),
        ("hnsw", {"quantize_type": "pq", "num_chunk": 9}, "between 1 and the vector dimension"),
        ("hnsw", {"quantize_type": "pq", "num_chunk": "4"}, "must be an integer"),
        ("hnsw", {"quantize_type": "pq", "num_bits": 6}, "must be 4 or 8"),
        ("ivf", {"quantize_type": "pq", "fast_scan": True}, "requires 'num_bits': 4"),
        ("ivf", {"quantize_type": "pq", "num_bits": 4, "fast_scan": 1}, "must be a boolean"),
        ("hnsw", {"quantize_type": "pq", "opq_iter": 2}, "requires 'enable_rotate': true"),
        (
            "hnsw",
            {"quantize_type": "pq", "enable_rotate": True, "opq_pq_iter": 0},
            "must be between 1 and 100",
        ),
        (
            "ivf",
            {"quantize_type": "pq", "enable_rotate": True, "opq_iter": 2**32},
            "must be between 1 and 100",
        ),
        (
            "ivf",
            {"quantize_type": "pq", "num_chunk": 3, "num_bits": 4, "fast_scan": True},
            "to divide the vector dimension (8)",
        ),
    ],
)
def test_bad_pq_params_raise(index: str, params: dict[str, object], match: str) -> None:
    assert match in _schema_error(index, params).message


def test_pq_default_chunks_must_fit_dimension() -> None:
    err = _schema_error("hnsw", {"quantize_type": "pq"}, dim=4)
    assert "(the default)" in err.message
    assert _index_param("hnsw", {"quantize_type": "pq", "num_chunk": 4}, dim=4)


def test_fast_scan_default_chunks_must_divide_dimension() -> None:
    params: dict[str, object] = {"quantize_type": "pq", "num_bits": 4, "fast_scan": True}
    err = _schema_error("ivf", params, dim=12)
    assert "(the default)" in err.message
    assert _index_param("ivf", {**params, "num_chunk": 6}, dim=12)
    # Without fast_scan, any chunk count up to dim is fine.
    assert _index_param("ivf", {"quantize_type": "pq", "num_chunk": 5}, dim=12)


def test_pq_requires_fp32_vectors() -> None:
    err = _schema_error("hnsw", {"quantize_type": "pq"}, dtype="VECTOR_FP16")
    assert "requires dtype 'VECTOR_FP32'" in err.message


def test_fast_scan_is_ivf_only() -> None:
    err = _schema_error("hnsw", {"quantize_type": "pq", "num_bits": 4, "fast_scan": True})
    assert err.details["unknown"] == ["fast_scan"]


@pytest.mark.parametrize(
    "params",
    [
        {"quantize_type": "int2"},
        {"quantize_type": "rabitq"},
        {"quantize_type": 8},
        {"quantize_type": "int8", "enable_rotate": "yes"},
        {"enable_rotate": True},
    ],
)
def test_bad_quantization_params_raise(params: dict[str, object]) -> None:
    with pytest.raises(SchemaValidationError):
        schema_mapper.build_collection_schema(
            "c", [VectorFieldSpec(name="emb", dim=8, params=params)], []
        )


def test_scalar_indexed_attaches_invert_index() -> None:
    schema = schema_mapper.build_collection_schema(
        "c",
        [VectorFieldSpec(name="emb", dim=2)],
        [
            ScalarFieldSpec(name="a", dtype="INT64", indexed=True),
            ScalarFieldSpec(name="b", dtype="INT64", indexed=False),
        ],
    )
    _, fields = col_adapter.schema_to_dicts(schema)
    by_name = {f["name"]: f for f in fields}
    assert by_name["a"].get("index_param") is not None
    assert by_name["b"].get("index_param") is None


def test_vector_dtype_must_be_vector() -> None:
    with pytest.raises(SchemaValidationError):
        schema_mapper.build_collection_schema(
            "c", [VectorFieldSpec(name="emb", dim=4, dtype="STRING")], []
        )


def test_scalar_dtype_must_be_scalar() -> None:
    with pytest.raises(SchemaValidationError):
        schema_mapper.build_collection_schema(
            "c",
            [VectorFieldSpec(name="emb", dim=4)],
            [ScalarFieldSpec(name="x", dtype="VECTOR_FP32")],
        )


def test_bad_metric_raises() -> None:
    with pytest.raises(SchemaValidationError):
        schema_mapper.build_collection_schema(
            "c", [VectorFieldSpec(name="emb", dim=4, metric="nope")], []
        )


def test_bad_index_param_type_raises() -> None:
    with pytest.raises(SchemaValidationError):
        schema_mapper.build_collection_schema(
            "c", [VectorFieldSpec(name="emb", dim=4, params={"m": "big"})], []
        )


@pytest.mark.parametrize(
    ("index", "params"),
    [
        ("hnsw", {"quantize": "int8"}),
        ("hnsw", {"n_list": 8}),
        ("flat", {"m": 16}),
        ("ivf", {"ef_construction": 100}),
    ],
)
def test_unknown_index_params_raise(index: str, params: dict[str, object]) -> None:
    with pytest.raises(SchemaValidationError, match="Unknown parameter"):
        schema_mapper.build_collection_schema(
            "c", [VectorFieldSpec(name="emb", dim=4, index=index, params=params)], []
        )


def test_primary_vector_info() -> None:
    req = CreateCollectionRequest(
        name="coll",
        vectors=[
            VectorFieldSpec(name="first", dim=128),
            VectorFieldSpec(name="second", dim=64),
        ],
    )
    assert schema_mapper.primary_vector_info(req) == ("first", 128)
