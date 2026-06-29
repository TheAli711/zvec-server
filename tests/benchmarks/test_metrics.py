"""Unit tests for benchmark measurement helpers (no engine, no network)."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from benchmarks.metrics import RssSampler, recall_at_k, summarize_latencies


def test_recall_at_k_partial_overlap() -> None:
    retrieved = [[1, 2, 3]]
    gt = np.array([[1, 2, 9]])
    # |{1,2,3} ∩ {1,2,9}| / 3 == 2/3
    assert recall_at_k(retrieved, gt, k=3) == pytest.approx(2 / 3)


def test_recall_at_k_perfect_and_truncated() -> None:
    retrieved = [[5, 6, 7, 8], [0, 1, 2, 3]]
    gt = np.array([[5, 6, 100, 200], [0, 1, 2, 3]])
    # k=2 considers only the first two of each row: row0 -> {5,6} all hit;
    # row1 -> {0,1} all hit. Mean recall@2 == 1.0
    assert recall_at_k(retrieved, gt, k=2) == pytest.approx(1.0)


def test_recall_at_k_empty_is_zero() -> None:
    assert recall_at_k([], np.empty((0, 3)), k=3) == 0.0


def test_recall_at_k_ignores_extra_ground_truth_columns() -> None:
    retrieved = [[1]]
    gt = np.array([[1, 2, 3, 4, 5]])
    assert recall_at_k(retrieved, gt, k=1) == pytest.approx(1.0)


def test_summarize_latencies_percentiles_ms() -> None:
    # 100 samples 1ms..100ms; p50 ~ 50ms, max == 100ms.
    latencies_s = [i / 1000 for i in range(1, 101)]
    stats = summarize_latencies(latencies_s)
    assert stats.count == 100
    assert stats.max_ms == pytest.approx(100.0)
    assert 49 <= stats.p50_ms <= 52
    assert stats.p99_ms >= stats.p95_ms >= stats.p90_ms >= stats.p50_ms


def test_summarize_latencies_empty() -> None:
    stats = summarize_latencies([])
    assert stats.count == 0
    assert stats.mean_ms == 0.0


def test_rss_sampler_none_pid_is_safe() -> None:
    # No target process: sampler must not start a thread or raise.
    with RssSampler(pid=None) as rss:
        pass
    assert rss.peak_mb == 0.0
