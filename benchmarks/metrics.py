"""Pure measurement helpers: recall@k, latency percentiles, throughput, RSS.

Nothing here touches Zvec or the network; it operates on already-collected
numbers so it is trivially unit-testable.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass

import numpy as np

__all__ = [
    "LatencyStats",
    "RssSampler",
    "recall_at_k",
    "summarize_latencies",
]


def recall_at_k(retrieved: list[list[int]], ground_truth: np.ndarray, k: int) -> float:
    """Mean recall@k over a set of queries.

    Args:
        retrieved: For each query, the retrieved neighbour ids (ints), best-first.
        ground_truth: ``(n_queries, >=k)`` array of true neighbour ids.
        k: Cutoff.

    Returns:
        Mean over queries of ``|retrieved[:k] ∩ truth[:k]| / k``. Empty input -> 0.
    """
    if not retrieved:
        return 0.0
    if len(retrieved) > ground_truth.shape[0]:
        raise ValueError("more result rows than ground-truth rows")
    total = 0.0
    for i, hits in enumerate(retrieved):
        truth = {int(x) for x in ground_truth[i, :k]}
        got = set(hits[:k])
        total += len(got & truth) / k
    return total / len(retrieved)


@dataclass(frozen=True)
class LatencyStats:
    """Summary of a batch of per-request latencies, in milliseconds."""

    count: int
    mean_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def summarize_latencies(latencies_s: list[float]) -> LatencyStats:
    """Turn a list of latencies (seconds) into a :class:`LatencyStats` (ms)."""
    if not latencies_s:
        return LatencyStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    arr = np.asarray(latencies_s, dtype=np.float64) * 1000.0
    p50, p90, p95, p99 = np.percentile(arr, [50, 90, 95, 99])
    return LatencyStats(
        count=int(arr.size),
        mean_ms=float(arr.mean()),
        p50_ms=float(p50),
        p90_ms=float(p90),
        p95_ms=float(p95),
        p99_ms=float(p99),
        max_ms=float(arr.max()),
    )


class RssSampler:
    """Samples a process's RSS in a background thread; reports peak and last.

    Used as a context manager around a measured phase. Falls back gracefully to
    zeros when ``psutil`` cannot see the target process.
    """

    def __init__(self, pid: int | None, interval_s: float = 0.1) -> None:
        self._pid = pid
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_mb = 0.0
        self.last_mb = 0.0

    def __enter__(self) -> RssSampler:
        if self._pid is not None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            import psutil

            proc = psutil.Process(self._pid)
        except Exception:
            return
        while not self._stop.is_set():
            try:
                mb = proc.memory_info().rss / (1024 * 1024)
            except Exception:
                break
            self.last_mb = mb
            self.peak_mb = max(self.peak_mb, mb)
            time.sleep(self._interval)
