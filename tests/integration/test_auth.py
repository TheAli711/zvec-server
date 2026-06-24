"""Integration tests for the API-key authentication middleware."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zvec_server.app import create_app
from zvec_server.config import Settings

API_KEY = "test-secret-key"


@pytest.fixture
def auth_client(tmp_path: Path) -> Iterator[TestClient]:
    """A TestClient for an app with API-key authentication enabled."""
    settings = Settings(
        data_dir=tmp_path / "data",
        log_level="WARNING",
        log_format="console",
        auth_enabled=True,
        api_key=API_KEY,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _bearer(key: str = API_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def test_health_endpoints_are_public(auth_client: TestClient) -> None:
    # Probes must work without credentials so orchestrators can poll them.
    assert auth_client.get("/healthz").status_code == 200
    assert auth_client.get("/readyz").status_code == 200


def test_missing_authorization_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.get("/collections")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    body = response.json()
    assert body["error"]["code"] == "unauthorized"


def test_wrong_scheme_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.get("/collections", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_invalid_key_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.get("/collections", headers=_bearer("not-the-key"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_valid_key_is_accepted(auth_client: TestClient) -> None:
    response = auth_client.get("/collections", headers=_bearer())
    assert response.status_code == 200


def test_full_write_flow_requires_and_accepts_key(auth_client: TestClient) -> None:
    body: dict[str, Any] = {
        "name": "secured",
        "vectors": [
            {"name": "embedding", "dim": 3, "dtype": "VECTOR_FP32", "index": "flat", "metric": "l2"}
        ],
    }
    # Without a key the create is blocked before reaching the route.
    assert auth_client.post("/collections", json=body).status_code == 401

    # With the key the full path works.
    created = auth_client.post("/collections", json=body, headers=_bearer())
    assert created.status_code == 201, created.text

    insert = auth_client.post(
        "/collections/secured/docs/insert",
        json={"docs": [{"id": "x", "vectors": {"embedding": [1.0, 0.0, 0.0]}}]},
        headers=_bearer(),
    )
    assert insert.status_code == 200, insert.text
    assert insert.json()["success_count"] == 1


def test_auth_disabled_allows_unauthenticated_requests(client: TestClient) -> None:
    # The default `client` fixture builds an app with auth disabled.
    assert client.get("/collections").status_code == 200
