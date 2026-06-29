"""Unit tests for exact ground-truth computation and its on-disk cache."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from benchmarks.groundtruth import cached_ground_truth, compute_ground_truth


def test_l2_nearest_neighbours() -> None:
    train = np.array([[0.0, 0.0], [1.0, 0.0], [5.0, 5.0]], dtype=np.float32)
    queries = np.array([[0.1, 0.0]], dtype=np.float32)
    gt = compute_ground_truth(train, queries, k=2, metric="l2")
    assert gt.tolist() == [[0, 1]]


def test_ip_ranks_by_dot_product() -> None:
    train = np.array([[1.0, 0.0], [0.0, 1.0], [2.0, 0.0]], dtype=np.float32)
    queries = np.array([[1.0, 0.0]], dtype=np.float32)
    gt = compute_ground_truth(train, queries, k=2, metric="ip")
    # dots = [1, 0, 2] -> nearest (largest) is index 2 then 0.
    assert gt.tolist() == [[2, 0]]


def test_cosine_ignores_magnitude() -> None:
    train = np.array([[10.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    queries = np.array([[1.0, 0.0]], dtype=np.float32)
    gt = compute_ground_truth(train, queries, k=1, metric="cosine")
    assert gt.tolist() == [[0]]


def test_batched_matches_unbatched() -> None:
    rng = np.random.default_rng(0)
    train = rng.standard_normal((300, 8), dtype=np.float32)
    queries = rng.standard_normal((50, 8), dtype=np.float32)
    a = compute_ground_truth(train, queries, k=5, metric="l2", query_batch=7)
    b = compute_ground_truth(train, queries, k=5, metric="l2", query_batch=1000)
    assert np.array_equal(a, b)


def test_cache_writes_then_reads(tmp_path) -> None:
    rng = np.random.default_rng(1)
    train = rng.standard_normal((100, 4), dtype=np.float32)
    queries = rng.standard_normal((10, 4), dtype=np.float32)
    first = cached_ground_truth(train, queries, k=3, metric="l2", cache_dir=tmp_path)
    cached_files = list(tmp_path.glob("gt-*.npy"))
    assert len(cached_files) == 1
    second = cached_ground_truth(train, queries, k=3, metric="l2", cache_dir=tmp_path)
    assert np.array_equal(first, second)
    # No new file created on the cache hit.
    assert list(tmp_path.glob("gt-*.npy")) == cached_files
