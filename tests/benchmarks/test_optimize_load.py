"""Unit tests for the optimize-load benchmark's search loop."""

from __future__ import annotations

import threading

import pytest

np = pytest.importorskip("numpy")

from benchmarks.optimize_load import _window, search_until
from benchmarks.runners.base import SearchOutcome


class _FakeRunner:
    name = "fake"

    def __init__(self, stop_after: int, stop: threading.Event) -> None:
        self.calls = 0
        self._stop_after = stop_after
        self._stop = stop
        self._lock = threading.Lock()

    def search(self, vector: object, topk: int, **_: object) -> SearchOutcome:
        with self._lock:
            self.calls += 1
            if self.calls >= self._stop_after:
                self._stop.set()
        return SearchOutcome(ids=[])


def test_search_until_runs_until_stopped() -> None:
    stop = threading.Event()
    runner = _FakeRunner(stop_after=50, stop=stop)
    latencies, seconds = search_until(
        runner,  # type: ignore[arg-type]
        np.zeros((3, 4), dtype=np.float32),
        concurrency=4,
        topk=10,
        ef=None,
        stop=stop,
    )
    assert len(latencies) == runner.calls >= 50
    assert seconds > 0


def test_window_summarizes_and_handles_empty() -> None:
    window = _window([0.001, 0.002, 0.004], 1.0)
    assert window["queries"] == 3 and window["qps"] == 3.0
    assert window["max_ms"] == pytest.approx(4.0)
    assert _window([], 1.0)["max_ms"] is None
