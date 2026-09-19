"""Integration tests for document write/fetch/delete/export endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zvec_server.api import vectors as vectors_api


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


def _export_lines(response: Any) -> list[dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines()]


def test_export_streams_every_doc_as_ndjson_and_reimports(
    client: TestClient,
    created_collection: str,
    collection_body: dict[str, Any],
    sample_docs: list[dict[str, Any]],
) -> None:
    assert _insert(client, created_collection, sample_docs).json()["success_count"] == 3
    response = client.get(f"/collections/{created_collection}/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = _export_lines(response)
    assert sorted(line["id"] for line in lines) == ["a", "b", "c"]
    for line in lines:
        assert set(line) == {"id", "vectors", "fields"}  # DocIn shape, no score

    # The export feeds straight back into insert.
    collection_body["name"] = "restored"
    assert client.post("/collections", json=collection_body).status_code == 201
    restored = client.post("/collections/restored/docs/insert", json={"docs": lines})
    assert restored.json()["success_count"] == 3
    doc = client.get("/collections/restored/docs/a", params={"include_vector": True}).json()
    original = next(d for d in sample_docs if d["id"] == "a")
    assert doc["fields"] == original["fields"]
    assert doc["vectors"]["embedding"] == pytest.approx(original["vectors"]["embedding"])


def test_export_without_vectors_and_with_output_fields(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    client.post(f"/collections/{created_collection}/docs/insert", json={"docs": sample_docs})
    response = client.get(
        f"/collections/{created_collection}/export",
        params={"include_vector": False, "output_fields": ["year"]},
    )
    assert response.status_code == 200, response.text
    for line in _export_lines(response):
        assert "vectors" not in line
        assert set(line["fields"]) == {"year"}


def test_export_empty_collection(client: TestClient, created_collection: str) -> None:
    response = client.get(f"/collections/{created_collection}/export")
    assert response.status_code == 200
    assert response.text == ""


def test_export_spans_multiple_batches(
    client: TestClient, created_collection: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vectors_api, "EXPORT_BATCH_SIZE", 2)
    docs = [
        {
            "id": str(i),
            "vectors": {"embedding": [0.1, 0.2, 0.3, 0.4]},
            "fields": {"category": "tech", "year": 2020 + i},
        }
        for i in range(7)
    ]
    assert _insert(client, created_collection, docs).json()["success_count"] == 7
    lines = _export_lines(client.get(f"/collections/{created_collection}/export"))
    assert sorted(int(line["id"]) for line in lines) == list(range(7))


def test_export_unknown_output_field_returns_400(
    client: TestClient, created_collection: str
) -> None:
    response = client.get(
        f"/collections/{created_collection}/export", params={"output_fields": ["nope"]}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_argument"


def test_export_missing_collection_returns_404(client: TestClient) -> None:
    assert client.get("/collections/nope_col/export").status_code == 404


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
def test_export_client_disconnect_releases_cursor(
    client: TestClient,
    created_collection: str,
    sample_docs: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    spec_version: str,
) -> None:
    """A client hanging up mid-export releases the snapshot cursor promptly,
    without waiting for garbage collection (TestClient buffers streams, so this
    drives the ASGI app directly)."""
    monkeypatch.setattr(vectors_api, "EXPORT_BATCH_SIZE", 1)
    _insert(client, created_collection, sample_docs)
    managed = client.app.state.manager.get(created_collection)  # type: ignore[attr-defined]

    async def _run() -> None:
        first_chunk = asyncio.Event()
        received = 0

        async def receive() -> dict[str, Any]:
            nonlocal received
            received += 1
            if received == 1:
                return {"type": "http.request", "body": b"", "more_body": False}
            await first_chunk.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                if first_chunk.is_set() and spec_version == "2.4":
                    raise OSError("client went away")
                first_chunk.set()
                await asyncio.sleep(0)  # let the disconnect be observed

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec_version},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": f"/collections/{created_collection}/export",
            "raw_path": f"/collections/{created_collection}/export".encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        }
        with contextlib.suppress(Exception):
            await client.app(scope, receive, send)  # type: ignore[arg-type]

    gc.disable()  # prove release doesn't rely on the GC finalizing the generator
    try:
        client.portal.call(_run)  # type: ignore[union-attr]
        assert managed.cursors == set()
    finally:
        gc.enable()
