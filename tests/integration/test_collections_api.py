"""Integration tests for the collection management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_create_collection(client: TestClient, collection_body: dict[str, Any]) -> None:
    response = client.post("/collections", json=collection_body)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "articles"
    assert body["embedding_dimension"] == 4
    assert body["embedding_model"] == "test-model"
    assert body["available"] is True
    assert body["stats"]["doc_count"] == 0
    assert len(body["vectors"]) == 1
    assert len(body["fields"]) == 2


def test_create_duplicate_returns_409(client: TestClient, collection_body: dict[str, Any]) -> None:
    assert client.post("/collections", json=collection_body).status_code == 201
    dup = client.post("/collections", json=collection_body)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "collection_already_exists"


def test_create_invalid_name_returns_422(client: TestClient) -> None:
    response = client.post(
        "/collections",
        json={"name": "bad name!", "vectors": [{"name": "e", "dim": 4}]},
    )
    assert response.status_code == 422


def test_create_invalid_dtype_returns_422(client: TestClient) -> None:
    response = client.post(
        "/collections",
        json={"name": "bad", "vectors": [{"name": "e", "dim": 4, "dtype": "NOPE"}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "schema_validation_error"


def test_create_scalar_dtype_as_vector_returns_422(client: TestClient) -> None:
    response = client.post(
        "/collections",
        json={"name": "bad", "vectors": [{"name": "e", "dim": 4, "dtype": "STRING"}]},
    )
    assert response.status_code == 422


def test_list_collections(client: TestClient, created_collection: str) -> None:
    response = client.get("/collections")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()["collections"]]
    assert created_collection in names


def test_get_collection(client: TestClient, created_collection: str) -> None:
    response = client.get(f"/collections/{created_collection}")
    assert response.status_code == 200
    assert response.json()["name"] == created_collection


def test_get_missing_collection_returns_404(client: TestClient) -> None:
    response = client.get("/collections/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "collection_not_found"


def test_delete_collection(client: TestClient, created_collection: str) -> None:
    response = client.delete(f"/collections/{created_collection}")
    assert response.status_code == 200
    assert "deleted" in response.json()["message"]
    assert client.get(f"/collections/{created_collection}").status_code == 404


def test_delete_missing_collection_returns_404(client: TestClient) -> None:
    assert client.delete("/collections/missing").status_code == 404


def test_flush_and_optimize(client: TestClient, created_collection: str) -> None:
    assert client.post(f"/collections/{created_collection}/flush").status_code == 200
    assert client.post(f"/collections/{created_collection}/optimize").status_code == 200
