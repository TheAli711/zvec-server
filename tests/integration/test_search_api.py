"""Integration tests for the similarity-search endpoint and persistence reload."""

from __future__ import annotations

from typing import Any

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
