"""Shared pytest fixtures.

Each test gets an isolated temporary data directory and a freshly built app.
The Zvec engine initializes once per process (the runtime guard makes repeated
app startups safe), so tests run against the real engine in ``tmp_path``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zvec_server.app import create_app
from zvec_server.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Server settings pointed at an isolated temporary data directory."""
    return Settings(
        data_dir=tmp_path / "data",
        log_level="WARNING",
        log_format="console",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A TestClient whose lifespan (startup/shutdown) runs around the test."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def collection_body() -> dict[str, Any]:
    """A small but representative create-collection request body."""
    return {
        "name": "articles",
        "vectors": [
            {
                "name": "embedding",
                "dim": 4,
                "dtype": "VECTOR_FP32",
                "index": "hnsw",
                "metric": "cosine",
            }
        ],
        "fields": [
            {"name": "category", "dtype": "STRING", "indexed": True},
            {"name": "year", "dtype": "INT64", "indexed": True},
        ],
        "embedding_model": "test-model",
    }


@pytest.fixture
def created_collection(client: TestClient, collection_body: dict[str, Any]) -> str:
    """Create the sample collection and return its name."""
    response = client.post("/collections", json=collection_body)
    assert response.status_code == 201, response.text
    return str(collection_body["name"])


@pytest.fixture
def sample_docs() -> list[dict[str, Any]]:
    """A handful of documents matching the sample collection schema."""
    return [
        {
            "id": "a",
            "vectors": {"embedding": [0.1, 0.2, 0.3, 0.4]},
            "fields": {"category": "tech", "year": 2021},
        },
        {
            "id": "b",
            "vectors": {"embedding": [0.2, 0.1, 0.0, 0.9]},
            "fields": {"category": "news", "year": 2019},
        },
        {
            "id": "c",
            "vectors": {"embedding": [0.9, 0.8, 0.7, 0.6]},
            "fields": {"category": "tech", "year": 2023},
        },
    ]
