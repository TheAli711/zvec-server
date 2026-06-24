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
                name="emb", dim=4, index="ivf", metric="l2", params={"n_list": 16, "n_iters": 7}
            )
        ],
        [],
    )
    vectors, _ = col_adapter.schema_to_dicts(schema)
    index = vectors[0]["index_param"]
    assert index["type"] == "IVF"
    assert index["n_list"] == 16
    assert index["n_iters"] == 7


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


def test_primary_vector_info() -> None:
    req = CreateCollectionRequest(
        name="c",
        vectors=[
            VectorFieldSpec(name="first", dim=128),
            VectorFieldSpec(name="second", dim=64),
        ],
    )
    assert schema_mapper.primary_vector_info(req) == ("first", 128)
