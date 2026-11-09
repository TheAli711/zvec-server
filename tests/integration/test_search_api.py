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


@pytest.mark.parametrize("index", ["flat", "ivf"])
def test_quantized_collection_roundtrip(
    client: TestClient,
    collection_body: dict[str, Any],
    sample_docs: list[dict[str, Any]],
    index: str,
) -> None:
    collection_body["vectors"][0]["index"] = index
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


def test_hnsw_rotation_rejected_until_upstream_fix(
    client: TestClient, collection_body: dict[str, Any]
) -> None:
    """ZS-069: Zvec 0.8 returns wrong results for new hnsw + int8 + rotation."""
    collection_body["vectors"][0]["params"] = {"quantize_type": "int8", "enable_rotate": True}
    response = client.post("/collections", json=collection_body)
    assert response.status_code == 422, response.text
    assert "Zvec 0.8 returns wrong results" in response.json()["error"]["message"]
    assert client.get("/collections/articles").status_code == 404


def _random_docs(n: int, dim: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [
        {"id": str(i), "vectors": {"embedding": [rng.gauss(0, 1) for _ in range(dim)]}}
        for i in range(n)
    ]


@pytest.mark.parametrize(
    ("index", "params", "query_params"),
    [
        ("hnsw", {"quantize_type": "uniform_uint4"}, {"is_using_refiner": True}),
        ("hnsw", {"quantize_type": "uniform_uint7"}, {"is_using_refiner": True}),
        ("hnsw", {"quantize_type": "uniform_uint8"}, None),
        ("hnsw", {"quantize_type": "pq", "num_chunk": 8}, {"is_using_refiner": True}),
        (
            "hnsw",
            {"quantize_type": "pq", "num_chunk": 8, "num_bits": 4, "enable_rotate": True},
            {"is_using_refiner": True, "scale_factor": 4},
        ),
        (
            "ivf",
            {"n_list": 4, "quantize_type": "pq", "num_chunk": 8},
            {"nprobe": 4, "is_using_refiner": True, "scale_factor": 10},
        ),
        (
            "ivf",
            {"n_list": 4, "quantize_type": "pq", "num_chunk": 8, "num_bits": 4, "fast_scan": True},
            {"nprobe": 4, "is_using_refiner": True, "scale_factor": 50},
        ),
    ],
)
def test_new_quantizers_find_exact_match(
    client: TestClient,
    index: str,
    params: dict[str, Any],
    query_params: dict[str, Any] | None,
) -> None:
    body = {
        "name": "q_col",
        "vectors": [
            {"name": "embedding", "dim": 16, "index": index, "metric": "l2", "params": params}
        ],
    }
    created = client.post("/collections", json=body)
    assert created.status_code == 201, created.text
    index_param = created.json()["vectors"][0]["index_param"]
    assert index_param["quantize_type"] == params["quantize_type"].upper()
    for key in ("num_chunk", "num_bits", "fast_scan", "enable_rotate"):
        if key in params:
            assert index_param["quantizer_param"][key] == params[key]

    docs = _random_docs(300, 16, seed=11)
    _seed(client, "q_col", docs)
    assert client.post("/collections/q_col/optimize").status_code == 200
    for target in ("7", "123"):
        response = client.post(
            "/collections/q_col/search",
            json={
                "queries": [
                    {
                        "field": "embedding",
                        "vector": docs[int(target)]["vectors"]["embedding"],
                        "params": query_params,
                    }
                ],
                "topk": 3,
            },
        )
        assert response.status_code == 200, response.text
        top = response.json()["results"][0]
        assert top["id"] == target
        if params["quantize_type"] == "pq" and query_params:
            # Only the refiner re-scores against the full vectors; PQ distances
            # alone are approximate, so an exact 0 proves the refiner ran.
            assert top["score"] == pytest.approx(0.0, abs=1e-6)


def test_refiner_on_unquantized_hnsw_returns_400(
    client: TestClient, collection_body: dict[str, Any], sample_docs: list[dict[str, Any]]
) -> None:
    """ZS-072: the engine fails after optimize; reject up front instead of a 500."""
    assert client.post("/collections", json=collection_body).status_code == 201
    _seed(client, "articles", sample_docs)
    assert client.post("/collections/articles/optimize").status_code == 200
    response = _search(client, "articles", {"is_using_refiner": True})
    assert response.status_code == 400, response.text
    assert "requires a quantized index" in response.json()["error"]["message"]
    # Turning it off explicitly, or tuning scale_factor alone, is still fine.
    assert _search(client, "articles", {"is_using_refiner": False}).status_code == 200
    assert _search(client, "articles", {"scale_factor": 2}).status_code == 200


@pytest.mark.parametrize(
    ("index", "params"),
    [
        ("ivf", {"is_using_refiner": True, "scale_factor": 10}),
        ("hnsw_int8", {"is_using_refiner": True, "scale_factor": 0}),
        ("hnsw_int8", {"ef": 32, "scale_factor": 2.5}),
    ],
)
def test_refiner_params_accepted(
    client: TestClient,
    collection_body: dict[str, Any],
    sample_docs: list[dict[str, Any]],
    index: str,
    params: dict[str, Any],
) -> None:
    if index == "hnsw_int8":
        collection_body["vectors"][0]["params"] = {"quantize_type": "int8"}
    else:
        collection_body["vectors"][0]["index"] = index
    assert client.post("/collections", json=collection_body).status_code == 201
    _seed(client, "articles", sample_docs)
    assert client.post("/collections/articles/optimize").status_code == 200
    response = _search(client, "articles", params)
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["id"] == "a"


def test_bad_quantize_type_returns_422(client: TestClient, collection_body: dict[str, Any]) -> None:
    collection_body["vectors"][0]["params"] = {"quantize_type": "int2"}
    response = client.post("/collections", json=collection_body)
    assert response.status_code == 422, response.text


# Zvec 0.8.1 builds RaBitQ for Linux and macOS (x86_64 and ARM64) and Windows x86_64.
RABITQ_SUPPORTED = sys.platform in ("linux", "darwin") or platform.machine() in (
    "x86_64",
    "AMD64",
)


@pytest.mark.parametrize("index", ["hnsw_rabitq", "ivf_rabitq"])
def test_rabitq_collection(client: TestClient, index: str) -> None:
    """RaBitQ works where the engine supports it and fails cleanly (422) elsewhere."""
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
        ("hnsw", {"scale_factor": -1}),
        ("hnsw", {"scale_factor": 1e9}),
        ("hnsw", {"scale_factor": "2"}),
        ("ivf", {"is_using_refiner": "yes"}),
        ("ivf", {"radius": 1.0}),
        ("flat", {"scale_factor": 2}),
    ],
)
def test_search_bad_query_params_return_400(
    client: TestClient, collection_body: dict[str, Any], index: str, params: dict[str, Any]
) -> None:
    collection_body["vectors"][0]["index"] = index
    assert client.post("/collections", json=collection_body).status_code == 201
    response = _search(client, "articles", params)
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("param", ["scale_factor", "radius"])
def test_search_non_finite_float_params_return_400(
    client: TestClient, collection_body: dict[str, Any], raw: str, param: str
) -> None:
    """The JSON parser accepts NaN/Infinity literals; the engine would 500 on them."""
    collection_body["vectors"][0]["params"] = {"quantize_type": "int8"}
    assert client.post("/collections", json=collection_body).status_code == 201
    body = (
        '{"queries": [{"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4], '
        f'"params": {{"is_using_refiner": true, "{param}": {raw}}}}}]}}'
    )
    response = client.post(
        "/collections/articles/search",
        content=body,
        headers={"content-type": "application/json"},
    )
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


def test_new_index_params_survive_restart(settings: Settings) -> None:
    """Quantized HNSW and SOAR IVF collections reopen with their params intact,
    and per-index search params still apply after the reload."""
    specs = {
        "quant_hnsw": {"index": "hnsw", "params": {"quantize_type": "int4"}},
        "soar_ivf": {"index": "ivf", "params": {"n_list": 4, "use_soar": True}},
        "rot_flat": {"index": "flat", "params": {"quantize_type": "int4", "enable_rotate": True}},
        "uniform_hnsw": {
            "index": "hnsw",
            "metric": "l2",
            "params": {"quantize_type": "uniform_uint8"},
        },
        "pq_ivf": {
            "index": "ivf",
            "metric": "l2",
            "params": {
                "n_list": 4,
                "quantize_type": "pq",
                "num_chunk": 8,
                "num_bits": 4,
                "fast_scan": True,
            },
        },
    }
    rng = random.Random(3)
    docs = [
        {"id": str(i), "vectors": {"embedding": [rng.random() for _ in range(16)]}}
        for i in range(300)
    ]
    with TestClient(create_app(settings)) as first:
        for name, spec in specs.items():
            body = {"name": name, "vectors": [{"name": "embedding", "dim": 16, **spec}]}
            assert first.post("/collections", json=body).status_code == 201
            _seed(first, name, docs)
            assert first.post(f"/collections/{name}/optimize").status_code == 200
        before = {n: first.get(f"/collections/{n}").json()["vectors"] for n in specs}

    with TestClient(create_app(settings)) as second:
        for name in specs:
            info = second.get(f"/collections/{name}").json()
            assert info["available"] is True
            assert info["vectors"] == before[name]
            assert info["stats"]["doc_count"] == 300
        assert before["quant_hnsw"][0]["index_param"]["quantize_type"] == "INT4"
        rot = before["rot_flat"][0]["index_param"]
        assert (rot["quantize_type"], rot["quantizer_param"]["enable_rotate"]) == ("INT4", True)
        assert before["soar_ivf"][0]["index_param"]["use_soar"] is True
        assert before["uniform_hnsw"][0]["index_param"]["quantize_type"] == "UNIFORM_UINT8"
        pq = before["pq_ivf"][0]["index_param"]
        assert pq["quantize_type"] == "PQ"
        assert {k: pq["quantizer_param"][k] for k in ("num_chunk", "num_bits", "fast_scan")} == {
            "num_chunk": 8,
            "num_bits": 4,
            "fast_scan": True,
        }

        for name, params in [
            ("quant_hnsw", {"ef": 64}),
            ("soar_ivf", {"nprobe": 4}),
            ("rot_flat", None),
            ("uniform_hnsw", {"ef": 64, "is_using_refiner": True}),
            ("pq_ivf", {"nprobe": 4, "is_using_refiner": True, "scale_factor": 20}),
        ]:
            response = second.post(
                f"/collections/{name}/search",
                json={"queries": [{"field": "embedding", "id": "7", "params": params}], "topk": 3},
            )
            assert response.status_code == 200, response.text
            assert len(response.json()["results"]) == 3


def test_group_by_search_output_options(
    client: TestClient, created_collection: str, sample_docs: list[dict[str, Any]]
) -> None:
    _seed(client, created_collection, sample_docs)
    response = client.post(
        f"/collections/{created_collection}/search/group-by",
        json={
            "query": {"field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4]},
            "group_by": "category",
            "include_vector": True,
            "output_fields": ["year"],
        },
    )
    assert response.status_code == 200, response.text
    hits = [hit for group in response.json()["groups"] for hit in group["results"]]
    assert len(hits) == 3
    by_id = {d["id"]: d for d in sample_docs}
    for hit in hits:
        assert set(hit["fields"]) == {"year"}
        assert hit["vectors"]["embedding"] == pytest.approx(
            by_id[hit["id"]]["vectors"]["embedding"]
        )
