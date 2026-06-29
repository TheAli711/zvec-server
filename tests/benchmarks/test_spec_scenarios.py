"""Unit tests for collection specs, the search grid, and scenario building."""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from benchmarks.scenarios import SearchGrid, build_scenario
from benchmarks.spec import CollectionSpec


def test_index_params_hnsw() -> None:
    spec = CollectionSpec(name="c", dim=8, index="hnsw", m=16, ef_construction=200)
    assert spec.index_params() == {"m": 16, "ef_construction": 200}


def test_index_params_ivf() -> None:
    spec = CollectionSpec(name="c", dim=8, index="ivf", n_list=100)
    assert spec.index_params() == {"n_list": 100}


def test_index_params_flat_is_none() -> None:
    assert CollectionSpec(name="c", dim=8, index="flat").index_params() is None


def test_spec_defaults_mmap_off() -> None:
    # Benchmarks default to mmap off for clean recall (zvec 0.5.0 quirk).
    assert CollectionSpec(name="c", dim=8).enable_mmap is False


def test_search_grid_cartesian_product() -> None:
    grid = SearchGrid(topk=(10,), ef=(32, 128), concurrency=(1, 8))
    points = grid.points()
    assert len(points) == 4
    assert {(p.ef, p.concurrency) for p in points} == {(32, 1), (32, 8), (128, 1), (128, 8)}


def test_build_smoke_scenario() -> None:
    scenario = build_scenario("smoke")
    assert scenario.name == "smoke"
    assert scenario.spec.dim == 64
    assert scenario.grid.points()  # non-empty


def test_cohere_requires_hdf5() -> None:
    with pytest.raises(ValueError, match="requires --hdf5"):
        build_scenario("cohere1m")


def test_unknown_scenario_raises() -> None:
    with pytest.raises(ValueError, match="unknown scenario"):
        build_scenario("nope")
