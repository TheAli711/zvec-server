"""Unit tests for :mod:`zvec_server.adapter.schema_mapper`."""

from __future__ import annotations

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


@pytest.mark.parametrize("index", ["hnsw", "flat", "ivf"])
@pytest.mark.parametrize("quantize", ["fp16", "int8", "INT4"])
def test_build_schema_quantization(index: str, quantize: str) -> None:
    schema = schema_mapper.build_collection_schema(
        "c",
        [
            VectorFieldSpec(
                name="emb",
                dim=8,
                index=index,
                params={"quantize_type": quantize, "enable_rotate": True},
            )
        ],
        [],
    )
    vectors, _ = col_adapter.schema_to_dicts(schema)
    index_param = vectors[0]["index_param"]
    assert index_param["quantize_type"] == quantize.upper()
    assert index_param["quantizer_param"] == {"enable_rotate": True}


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
        name="c",
        vectors=[
            VectorFieldSpec(name="first", dim=128),
            VectorFieldSpec(name="second", dim=64),
        ],
    )
    assert schema_mapper.primary_vector_info(req) == ("first", 128)
