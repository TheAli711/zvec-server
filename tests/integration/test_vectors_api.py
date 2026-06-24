"""Integration tests for document write/fetch/delete endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


def _insert(client: TestClient, name: str, docs: list[dict[str, Any]]) -> Any:
    return client.post(f"/collections/{name}/docs/insert", json={"docs": docs})


def test_insert_documents(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    response = _insert(client, created_collection, sample_docs)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 3
    assert body["error_count"] == 0
    assert [r["id"] for r in body["results"]] == ["a", "b", "c"]


def test_insert_autogenerates_id(client: TestClient, created_collection: str) -> None:
    response = _insert(
        client,
        created_collection,
        [
            {
                "vectors": {"embedding": [0.1, 0.2, 0.3, 0.4]},
                "fields": {"category": "tech", "year": 2024},
            }
        ],
    )
    assert response.status_code == 200
    generated_id = response.json()["results"][0]["id"]
    assert generated_id and isinstance(generated_id, str)


def test_insert_into_missing_collection_returns_404(client: TestClient) -> None:
    response = _insert(client, "missing", [{"vectors": {"embedding": [0.1, 0.2, 0.3, 0.4]}}])
    assert response.status_code == 404


def test_fetch_documents(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _insert(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/docs/fetch",
        json={"ids": ["a", "b", "missing"], "include_vector": True},
    )
    assert response.status_code == 200
    docs = response.json()["docs"]
    assert set(docs) == {"a", "b"}
    assert docs["a"]["fields"]["category"] == "tech"
    # VECTOR_FP32 storage loses precision, so compare approximately.
    assert docs["a"]["vectors"]["embedding"] == pytest.approx([0.1, 0.2, 0.3, 0.4], abs=1e-6)


def test_get_single_document(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _insert(client, created_collection, sample_docs)
    response = client.get(f"/collections/{created_collection}/docs/a")
    assert response.status_code == 200
    assert response.json()["id"] == "a"


def test_get_missing_document_returns_404(client: TestClient, created_collection: str) -> None:
    response = client.get(f"/collections/{created_collection}/docs/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


def test_update_document(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _insert(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/docs/update",
        json={"docs": [{"id": "a", "fields": {"year": 2099}}]},
    )
    assert response.status_code == 200
    assert response.json()["success_count"] == 1
    fetched = client.get(f"/collections/{created_collection}/docs/a").json()
    assert fetched["fields"]["year"] == 2099


def test_upsert_document(client: TestClient, created_collection: str) -> None:
    response = client.post(
        f"/collections/{created_collection}/docs/upsert",
        json={
            "docs": [
                {
                    "id": "z",
                    "vectors": {"embedding": [1, 0, 0, 0]},
                    "fields": {"category": "x", "year": 2020},
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["success_count"] == 1


def test_delete_by_ids(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _insert(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/docs/delete",
        json={"ids": ["a", "b"]},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    fetched = client.post(
        f"/collections/{created_collection}/docs/fetch", json={"ids": ["a", "b", "c"]}
    ).json()
    assert set(fetched["docs"]) == {"c"}


def test_delete_by_filter(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _insert(client, created_collection, sample_docs)
    client.post(f"/collections/{created_collection}/flush")
    response = client.post(
        f"/collections/{created_collection}/docs/delete",
        json={"filter": "year < 2020"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_delete_requires_exactly_one_returns_422(
    client: TestClient, created_collection: str
) -> None:
    neither = client.post(f"/collections/{created_collection}/docs/delete", json={})
    assert neither.status_code == 422
    both = client.post(
        f"/collections/{created_collection}/docs/delete",
        json={"ids": ["a"], "filter": "year > 0"},
    )
    assert both.status_code == 422
