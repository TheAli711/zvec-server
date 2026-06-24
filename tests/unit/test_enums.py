"""Unit tests for the adapter enum-translation helpers."""

from __future__ import annotations

import pytest
import zvec

from zvec_server.adapter import enums
from zvec_server.errors import SchemaValidationError


def test_parse_data_type_case_insensitive() -> None:
    assert enums.parse_data_type("vector_fp32") is zvec.DataType.VECTOR_FP32
    assert enums.parse_data_type("STRING") is zvec.DataType.STRING


def test_parse_data_type_unknown_raises() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        enums.parse_data_type("NOT_A_TYPE")
    assert "valid" in (exc.value.details or {})


def test_parse_metric_type_aliases() -> None:
    assert enums.parse_metric_type("cosine") is zvec.MetricType.COSINE
    assert enums.parse_metric_type("dot") is zvec.MetricType.IP
    assert enums.parse_metric_type("inner_product") is zvec.MetricType.IP
    assert enums.parse_metric_type("euclidean") is zvec.MetricType.L2
    assert enums.parse_metric_type("L2") is zvec.MetricType.L2


def test_parse_metric_type_unknown_raises() -> None:
    with pytest.raises(SchemaValidationError):
        enums.parse_metric_type("manhattan")


@pytest.mark.parametrize("name", ["hnsw", "HNSW", "Flat", "ivf"])
def test_validate_index_type_normalizes(name: str) -> None:
    assert enums.validate_index_type(name) == name.lower()


def test_validate_index_type_unknown_raises() -> None:
    with pytest.raises(SchemaValidationError):
        enums.validate_index_type("annoy")


def test_data_type_and_metric_names() -> None:
    assert enums.data_type_name(zvec.DataType.VECTOR_FP32) == "VECTOR_FP32"
    assert enums.metric_type_name(zvec.MetricType.COSINE) == "COSINE"


def test_is_vector_and_scalar_type() -> None:
    assert enums.is_vector_type("vector_fp32")
    assert not enums.is_vector_type("string")
    assert enums.is_scalar_type("STRING")
    assert not enums.is_scalar_type("vector_fp32")


def test_constants_present() -> None:
    assert "VECTOR_FP32" in enums.VECTOR_DATA_TYPES
    assert "STRING" in enums.SCALAR_DATA_TYPES
    assert frozenset({"hnsw", "flat", "ivf"}) == enums.INDEX_TYPES
