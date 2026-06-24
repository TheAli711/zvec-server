#!/usr/bin/env python3
"""End-to-end example client for Zvec Server using httpx.

This script walks through the full lifecycle against a running server:

    1. create a collection (4-dim embedding + a ``category`` scalar field)
    2. insert a few documents
    3. run a similarity search with a SQL-like filter
    4. fetch a document by id
    5. update a document
    6. delete a document
    7. drop the collection

Run a server first (see the project README), then::

    uv run python examples/python_client.py

Point at a different server with the ``ZVEC_SERVER_URL`` environment variable::

    ZVEC_SERVER_URL=http://localhost:8000 uv run python examples/python_client.py

If the server has authentication enabled, supply the API key and it will be sent
as a bearer token on every request::

    ZVEC_SERVER_API_KEY=your-key uv run python examples/python_client.py

The server stores client-supplied vectors only -- it does not generate
embeddings -- so the vectors below are hand-written for illustration.
"""

from __future__ import annotations

import os
import sys

import httpx

BASE_URL = os.environ.get("ZVEC_SERVER_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("ZVEC_SERVER_API_KEY")
COLLECTION = "articles_example"


def main() -> int:
    # Send the bearer token on every request when the server requires auth.
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    # A single client with a sane timeout, reused for every call.
    with httpx.Client(base_url=BASE_URL, timeout=30.0, headers=headers) as client:
        check_health(client)
        create_collection(client)
        try:
            insert_documents(client)
            search(client)
            fetch_by_id(client)
            update_document(client)
            delete_document(client)
        finally:
            # Always clean up, even if a step above failed.
            drop_collection(client)

    print("\nDone.")
    return 0


def _raise_for_status(resp: httpx.Response) -> httpx.Response:
    """Raise with the server's error body included, for readable failures."""
    if resp.is_error:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        req = resp.request
        raise RuntimeError(f"{req.method} {req.url} -> {resp.status_code}: {detail}")
    return resp


def check_health(client: httpx.Client) -> None:
    print(f"== Health check ({BASE_URL}) ==")
    resp = _raise_for_status(client.get("/healthz"))
    print(resp.json())


def create_collection(client: httpx.Client) -> None:
    print(f"\n== Create collection '{COLLECTION}' ==")
    payload = {
        "name": COLLECTION,
        "vectors": [
            {
                "name": "embedding",
                "dim": 4,
                "dtype": "VECTOR_FP32",
                "index": "hnsw",
                "metric": "cosine",
                "params": {"m": 16, "ef_construction": 200},
            }
        ],
        "fields": [
            {"name": "category", "dtype": "STRING", "indexed": True},
            {"name": "year", "dtype": "INT32", "indexed": True},
        ],
        "options": {"enable_mmap": True},
    }
    resp = _raise_for_status(client.post("/collections", json=payload))
    info = resp.json()
    print(f"created: name={info['name']} dim={info['embedding_dimension']} path={info['path']}")


def insert_documents(client: httpx.Client) -> None:
    print("\n== Insert documents ==")
    payload = {
        "docs": [
            {
                "id": "a1",
                "vectors": {"embedding": [0.10, 0.20, 0.30, 0.40]},
                "fields": {"category": "tech", "year": 2021},
            },
            {
                "id": "a2",
                "vectors": {"embedding": [0.12, 0.22, 0.29, 0.41]},
                "fields": {"category": "tech", "year": 2023},
            },
            {
                "id": "a3",
                "vectors": {"embedding": [0.90, 0.10, 0.05, 0.02]},
                "fields": {"category": "science", "year": 2019},
            },
        ]
    }
    resp = _raise_for_status(client.post(f"/collections/{COLLECTION}/docs/insert", json=payload))
    result = resp.json()
    print(f"inserted: success={result['success_count']} errors={result['error_count']}")


def search(client: httpx.Client) -> None:
    print("\n== Search (filter: category = 'tech' AND year > 2020) ==")
    # NOTE: filters use Zvec's SQL-like syntax -- single '=', single-quoted
    # strings, operators AND/OR/NOT/IN/BETWEEN/LIKE. NOT Python '=='.
    payload = {
        "queries": [
            {"field": "embedding", "vector": [0.11, 0.21, 0.30, 0.40], "params": {"ef": 64}}
        ],
        "topk": 3,
        "filter": "category = 'tech' AND year > 2020",
        "include_vector": False,
        "output_fields": ["category", "year"],
    }
    resp = _raise_for_status(client.post(f"/collections/{COLLECTION}/search", json=payload))
    for hit in resp.json()["results"]:
        print(f"  id={hit['id']} score={hit['score']} fields={hit['fields']}")


def fetch_by_id(client: httpx.Client) -> None:
    print("\n== Fetch document by id (a1) ==")
    resp = _raise_for_status(
        client.get(f"/collections/{COLLECTION}/docs/a1", params={"include_vector": True})
    )
    doc = resp.json()
    print(f"  id={doc['id']} fields={doc['fields']} vectors={doc['vectors']}")


def update_document(client: httpx.Client) -> None:
    print("\n== Update document (a1 -> year 2022) ==")
    payload = {
        "docs": [
            {
                "id": "a1",
                "vectors": {"embedding": [0.10, 0.20, 0.30, 0.40]},
                "fields": {"category": "tech", "year": 2022},
            }
        ]
    }
    resp = _raise_for_status(client.post(f"/collections/{COLLECTION}/docs/update", json=payload))
    result = resp.json()
    print(f"updated: success={result['success_count']} errors={result['error_count']}")


def delete_document(client: httpx.Client) -> None:
    print("\n== Delete document (a3) ==")
    resp = _raise_for_status(
        client.post(f"/collections/{COLLECTION}/docs/delete", json={"ids": ["a3"]})
    )
    print(f"  ok={resp.json()['ok']}")


def drop_collection(client: httpx.Client) -> None:
    print(f"\n== Drop collection '{COLLECTION}' ==")
    resp = client.delete(f"/collections/{COLLECTION}")
    if resp.status_code == 404:
        print("  (collection did not exist)")
        return
    _raise_for_status(resp)
    print(f"  {resp.json()['message']}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.ConnectError:
        print(
            f"ERROR: could not connect to {BASE_URL}. Is the server running?\n"
            "Start it with `uv run zvec-server` or `docker compose up`.",
            file=sys.stderr,
        )
        sys.exit(1)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
