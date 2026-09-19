"""Integration tests for the similarity-search endpoint and persistence reload."""

from __future__ import annotations

import platform
import random
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zvec_server.app import create_app
from zvec_server.config import Settings


def _seed(client: TestClient, name: str, docs: list[dict[str, Any]]) -> None:
    response = client.post(f"/collections/{name}/docs/insert", json={"docs": docs})
    assert response.status_code == 200, response.text
    client.post(f"/collections/{name}/flush")


def test_search_returns_hits(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _seed(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/search",
        json={"queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]}], "topk": 5},
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) >= 1
    assert any(r["id"] == "a" for r in results)


def test_search_with_filter(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _seed(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/search",
        json={
            "queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]}],
            "topk": 10,
            "filter": "category = 'tech'",
            "output_fields": ["category", "year"],
        },
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert results, "expected at least one tech hit"
    assert all(r["fields"]["category"] == "tech" for r in results)


def test_search_by_id(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _seed(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/search",
        json={"queries": [{"field": "embedding", "id": "a"}], "topk": 5},
    )
    assert response.status_code == 200, response.text
    assert any(r["id"] == "a" for r in response.json()["results"])


def test_search_bad_filter_returns_400(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _seed(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/search",
        json={
            "queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]}],
            "filter": "category == 'tech'",  # invalid: SQL-like uses single '='
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_argument"


def test_search_missing_collection_returns_404(client: TestClient) -> None:
    response = client.post(
        "/collections/missing/search",
        json={"queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]}]},
    )
    assert response.status_code == 404


def test_query_validation_requires_one_of_vector_or_id(
    client: TestClient, created_collection: str
) -> None:
    response = client.post(
        f"/collections/{created_collection}/search",
        json={"queries": [{"field": "embedding"}]},
    )
    assert response.status_code == 422


def test_persistence_reload(settings: Settings, collection_body: dict[str, Any]) -> None:
    """A new app on the same data dir reopens collections and their documents."""
    with TestClient(create_app(settings)) as first:
        assert first.post("/collections", json=collection_body).status_code == 201
        _seed(
            first,
            "articles",
            [
                {
                    "id": "a",
                    "vectors": {"embedding": [0.1, 0.2, 0.3, 0.4]},
                    "fields": {"category": "tech", "year": 2021},
                }
            ],
        )

    with TestClient(create_app(settings)) as second:
        info = second.get("/collections/articles")
        assert info.status_code == 200
        assert info.json()["stats"]["doc_count"] == 1
        search = second.post(
            "/collections/articles/search",
            json={"queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]}], "topk": 5},
        )
        assert search.status_code == 200
        assert any(r["id"] == "a" for r in search.json()["results"])


def test_quantized_collection_roundtrip(
    client: TestClient, collection_body: dict[str, Any], sample_docs: list[dict[str, Any]]
) -> None:
    collection_body["vectors"][0]["params"] = {"quantize_type": "int8", "enable_rotate": True}
    created = client.post("/collections", json=collection_body)
    assert created.status_code == 201, created.text
    index_param = created.json()["vectors"][0]["index_param"]
    assert index_param["quantize_type"] == "INT8"

    name = collection_body["name"]
    _seed(client, name, sample_docs)
    assert client.post(f"/collections/{name}/optimize").status_code == 200
    response = client.post(
        f"/collections/{name}/search",
        json={"queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]}], "topk": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["id"] == "a"


def test_bad_quantize_type_returns_422(client: TestClient, collection_body: dict[str, Any]) -> None:
    collection_body["vectors"][0]["params"] = {"quantize_type": "int2"}
    response = client.post("/collections", json=collection_body)
    assert response.status_code == 422, response.text


RABITQ_SUPPORTED = sys.platform == "linux" and platform.machine() in ("x86_64", "AMD64")


@pytest.mark.parametrize("index", ["hnsw_rabitq", "ivf_rabitq"])
def test_rabitq_collection(client: TestClient, index: str) -> None:
    """RaBitQ works on Linux x86_64 and fails cleanly (422) everywhere else."""
    body = {"name": "rq_col", "vectors": [{"name": "embedding", "dim": 64, "index": index}]}
    created = client.post("/collections", json=body)
    if not RABITQ_SUPPORTED:
        assert created.status_code == 422, created.text
        assert "not supported on this platform" in created.json()["error"]["message"]
        assert client.get("/collections/rq_col").status_code == 404
        return
    assert created.status_code == 201, created.text
    rng = random.Random(0)
    docs = [
        {"id": str(i), "vectors": {"embedding": [rng.random() for _ in range(64)]}}
        for i in range(200)
    ]
    _seed(client, "rq_col", docs)
    assert client.post("/collections/rq_col/optimize").status_code == 200
    response = client.post(
        "/collections/rq_col/search",
        json={"queries": [{"field": "embedding", "id": "7"}], "topk": 5},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["results"]) == 5


def _search(client: TestClient, name: str, params: dict[str, Any] | None) -> Any:
    return client.post(
        f"/collections/{name}/search",
        json={
            "queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4], "params": params}],
            "topk": 3,
        },
    )


@pytest.mark.parametrize(
    ("index", "params"),
    [
        ("hnsw", {"ef": 64, "is_linear": True, "is_using_refiner": False}),
        ("hnsw", {"radius": 10}),
        ("ivf", {"nprobe": 4}),
        ("flat", None),
    ],
)
def test_search_query_params_per_index(
    client: TestClient,
    collection_body: dict[str, Any],
    sample_docs: list[dict[str, Any]],
    index: str,
    params: dict[str, Any] | None,
) -> None:
    collection_body["vectors"][0]["index"] = index
    assert client.post("/collections", json=collection_body).status_code == 201
    _seed(client, "articles", sample_docs)
    response = _search(client, "articles", params)
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["id"] == "a"


@pytest.mark.parametrize(
    ("index", "params"),
    [
        ("flat", {"ef": 64}),
        ("ivf", {"ef": 64}),
        ("hnsw", {"nprobe": 4}),
        ("hnsw", {"ef": "64"}),
        ("hnsw", {"is_linear": 1}),
    ],
)
def test_search_bad_query_params_return_400(
    client: TestClient, collection_body: dict[str, Any], index: str, params: dict[str, Any]
) -> None:
    collection_body["vectors"][0]["index"] = index
    assert client.post("/collections", json=collection_body).status_code == 201
    response = _search(client, "articles", params)
    assert response.status_code == 400, response.text


def test_search_params_on_unknown_field_return_400(
    client: TestClient, created_collection: str
) -> None:
    response = client.post(
        f"/collections/{created_collection}/search",
        json={"queries": [{"field": "nope", "vector": [0.1] * 4, "params": {"ef": 8}}]},
    )
    assert response.status_code == 400, response.text


def test_group_by_search(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _seed(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/search/group-by",
        json={
            "query": {"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]},
            "group_by": "category",
            "group_count": 5,
            "topk_per_group": 1,
            "output_fields": ["category"],
        },
    )
    assert response.status_code == 200, response.text
    groups = response.json()["groups"]
    assert sorted(g["value"] for g in groups) == ["news", "tech"]
    for group in groups:
        assert len(group["results"]) == 1
        assert group["results"][0]["fields"]["category"] == group["value"]
    tech = next(g for g in groups if g["value"] == "tech")
    assert tech["results"][0]["id"] == "a"


def test_group_by_search_with_filter(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _seed(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/search/group-by",
        json={
            "query": {"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]},
            "group_by": "category",
            "filter": "year > 2020",
        },
    )
    assert response.status_code == 200, response.text
    groups = response.json()["groups"]
    assert [g["value"] for g in groups] == ["tech"]
    assert sorted(d["id"] for d in groups[0]["results"]) == ["a", "c"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"group_by": "nope"},
        {"filter": "year == = 1"},
        {"query": {"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4], "params": {"nprobe": 2}}},
    ],
)
def test_group_by_search_bad_request_returns_400(
    client: TestClient,
    created_collection: str,
    sample_docs: list[dict[str, Any]],
    overrides: dict[str, Any],
) -> None:
    # Zvec only validates group_by / filter when there is data to search.
    _seed(client, created_collection, sample_docs)
    body = {
        "query": {"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]},
        "group_by": "category",
        **overrides,
    }
    response = client.post(f"/collections/{created_collection}/search/group-by", json=body)
    assert response.status_code == 400, response.text


def test_group_by_unknown_field_on_empty_collection_returns_400(
    client: TestClient, created_collection: str
) -> None:
    response = client.post(
        f"/collections/{created_collection}/search/group-by",
        json={"query": {"field": "embedding", "vector": [0.1] * 4}, "group_by": "nope"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["valid"] == ["category", "year"]


def test_group_by_search_missing_collection_returns_404(client: TestClient) -> None:
    response = client.post(
        "/collections/nope_col/search/group-by",
        json={"query": {"field": "embedding", "vector": [0.1] * 4}, "group_by": "category"},
    )
    assert response.status_code == 404
