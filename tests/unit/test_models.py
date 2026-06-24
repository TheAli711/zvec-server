"""Unit tests for the Pydantic API models (validators and constraints)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zvec_server.models.collections import (
    CreateCollectionRequest,
    VectorFieldSpec,
)
from zvec_server.models.common import ErrorResponse
from zvec_server.models.search import QuerySpec, SearchRequest
from zvec_server.models.vectors import DeleteRequest, FetchRequest, WriteRequest

# --- CreateCollectionRequest name validation ---


@pytest.mark.parametrize("name", ["articles", "my-col_1", "A" * 128, "x"])
def test_collection_name_valid(name: str) -> None:
    req = CreateCollectionRequest(name=name, vectors=[VectorFieldSpec(name="emb", dim=4)])
    assert req.name == name


@pytest.mark.parametrize("name", ["", "has space", "bad/slash", "a" * 129, "emoji😀"])
def test_collection_name_invalid(name: str) -> None:
    with pytest.raises(ValidationError):
        CreateCollectionRequest(name=name, vectors=[VectorFieldSpec(name="emb", dim=4)])


def test_create_collection_requires_at_least_one_vector() -> None:
    with pytest.raises(ValidationError):
        CreateCollectionRequest(name="c", vectors=[])


def test_vector_dim_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        VectorFieldSpec(name="emb", dim=0)
    with pytest.raises(ValidationError):
        VectorFieldSpec(name="emb", dim=-1)


def test_vector_field_defaults() -> None:
    spec = VectorFieldSpec(name="emb", dim=4)
    assert spec.dtype == "VECTOR_FP32"
    assert spec.index == "hnsw"
    assert spec.metric == "cosine"
    assert spec.params is None


# --- DeleteRequest exactly-one-of ids/filter ---


def test_delete_request_ids_only() -> None:
    req = DeleteRequest(ids=["a", "b"])
    assert req.ids == ["a", "b"]
    assert req.filter is None


def test_delete_request_filter_only() -> None:
    req = DeleteRequest(filter="year > 2000")
    assert req.filter == "year > 2000"


def test_delete_request_neither_raises() -> None:
    with pytest.raises(ValidationError):
        DeleteRequest()


def test_delete_request_both_raises() -> None:
    with pytest.raises(ValidationError):
        DeleteRequest(ids=["a"], filter="year > 2000")


# --- QuerySpec exactly-one-of vector/id ---


def test_query_spec_vector_only() -> None:
    spec = QuerySpec(field="emb", vector=[1.0, 2.0])
    assert spec.vector == [1.0, 2.0]


def test_query_spec_id_only() -> None:
    spec = QuerySpec(field="emb", id="doc-1")
    assert spec.id == "doc-1"


def test_query_spec_neither_raises() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(field="emb")


def test_query_spec_both_raises() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(field="emb", vector=[1.0], id="doc-1")


# --- min_length constraints ---


def test_write_request_min_length() -> None:
    with pytest.raises(ValidationError):
        WriteRequest(docs=[])


def test_fetch_request_min_length() -> None:
    with pytest.raises(ValidationError):
        FetchRequest(ids=[])


def test_search_request_min_length() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(queries=[])


# --- SearchRequest topk bounds ---


def test_search_topk_default_and_bounds() -> None:
    req = SearchRequest(queries=[QuerySpec(field="emb", vector=[1.0])])
    assert req.topk == 10
    with pytest.raises(ValidationError):
        SearchRequest(queries=[QuerySpec(field="emb", vector=[1.0])], topk=0)
    with pytest.raises(ValidationError):
        SearchRequest(queries=[QuerySpec(field="emb", vector=[1.0])], topk=1001)


# --- ErrorResponse re-export ---


def test_error_response_reexported() -> None:
    err = ErrorResponse(error={"code": "x", "message": "y"})
    assert err.error.code == "x"
    assert err.error.message == "y"


# --- examples present in JSON schema (powers OpenAPI docs) ---


def test_models_carry_examples() -> None:
    for model in (CreateCollectionRequest, SearchRequest, DeleteRequest):
        schema = model.model_json_schema()
        assert "examples" in schema, f"{model.__name__} missing examples"
