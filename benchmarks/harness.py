"""The measurement driver: ingest, warmup, closed-loop concurrency, recall.

The harness is tier-agnostic — it only talks to the :class:`~benchmarks.runners.base.Runner`
protocol, so the same code measures the engine, in-process, and HTTP tiers
identically. Concurrency is closed-loop: ``N`` worker threads issue searches as
fast as they can for a fixed window (matching VectorDBBench's ``--num-concurrency``).

Recall is a property of ``(topk, ef, filter)`` and independent of concurrency, so
it is computed once per such key (sequential pass over all queries) and reused —
keeping the throughput passes pure timing.
"""

from __future__ import annotations

import itertools
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from benchmarks.datasets import Dataset
from benchmarks.metrics import RssSampler, recall_at_k, summarize_latencies
from benchmarks.results import IngestResult, SearchResult, TierResult
from benchmarks.runners.base import Runner
from benchmarks.scenarios import Scenario, SearchPoint

__all__ = ["measure_ingest", "measure_search", "run_tier"]


def measure_ingest(runner: Runner, dataset: Dataset, batch_size: int) -> IngestResult:
    """Load the full corpus in batches, then optimize; time each phase."""
    ids = dataset.doc_ids()
    vectors = dataset.train
    n = dataset.n
    with RssSampler(runner.target_pid()) as rss:
        t0 = time.perf_counter()
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            runner.ingest(ids[start:end], vectors[start:end], None)
        ingest_s = time.perf_counter() - t0

        t1 = time.perf_counter()
        runner.optimize()
        optimize_s = time.perf_counter() - t1

    return IngestResult(
        n_docs=n,
        batch_size=batch_size,
        seconds=ingest_s,
        docs_per_sec=(n / ingest_s) if ingest_s > 0 else 0.0,
        optimize_seconds=optimize_s,
        peak_rss_mb=rss.peak_mb,
    )


def _recall_pass(
    runner: Runner,
    queries: np.ndarray,
    ground_truth: np.ndarray,
    point: SearchPoint,
    recall_k: int,
    sample: int,
) -> float:
    """Sequential single-shot pass over a query sample to measure recall@k."""
    n = min(sample, queries.shape[0])
    retrieved: list[list[int]] = []
    for i in range(n):
        out = runner.search(
            queries[i],
            point.topk,
            ef=point.ef,
            nprobe=point.nprobe,
            filter=point.filter,
            include_vector=point.include_vector,
        )
        # Skip empty ids: zvec 0.5.0's mmap forward store can fail to resolve a
        # few freshly-optimized docs and return "" (see CollectionSpec.enable_mmap).
        retrieved.append([int(x) for x in out.ids if x])
    return recall_at_k(retrieved, ground_truth[:n], recall_k)


def measure_search(
    runner: Runner,
    queries: np.ndarray,
    ground_truth: np.ndarray,
    point: SearchPoint,
    *,
    recall_k: int,
    warmup_queries: int,
    measure_seconds: float,
    recall_cache: dict[tuple, float],
) -> SearchResult:
    """Measure QPS + latency at one grid point; recall is cached per (topk,ef,...)."""
    n_q = queries.shape[0]

    # Recall (concurrency-independent) — compute once, reuse across concurrency.
    rkey = (point.topk, point.ef, point.nprobe, point.filter, point.include_vector)
    if rkey not in recall_cache:
        recall_cache[rkey] = _recall_pass(
            runner, queries, ground_truth, point, recall_k, sample=min(n_q, 1000)
        )
    recall = recall_cache[rkey]

    # Warmup (discarded).
    for i in range(warmup_queries):
        runner.search(
            queries[i % n_q],
            point.topk,
            ef=point.ef,
            nprobe=point.nprobe,
            filter=point.filter,
            include_vector=point.include_vector,
        )

    counter = itertools.count()
    stop_at = time.perf_counter() + measure_seconds

    def worker() -> tuple[list[float], list[int], list[int]]:
        lat: list[float] = []
        req: list[int] = []
        resp: list[int] = []
        while time.perf_counter() < stop_at:
            i = next(counter) % n_q
            t0 = time.perf_counter()
            out = runner.search(
                queries[i],
                point.topk,
                ef=point.ef,
                nprobe=point.nprobe,
                filter=point.filter,
                include_vector=point.include_vector,
            )
            lat.append(time.perf_counter() - t0)
            if out.request_bytes is not None:
                req.append(out.request_bytes)
            if out.response_bytes is not None:
                resp.append(out.response_bytes)
        return lat, req, resp

    with RssSampler(runner.target_pid()) as rss:
        window_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=point.concurrency) as pool:
            results = list(pool.map(lambda _: worker(), range(point.concurrency)))
        window = time.perf_counter() - window_start

    latencies = [x for lat, _, _ in results for x in lat]
    req_bytes = [x for _, r, _ in results for x in r]
    resp_bytes = [x for _, _, r in results for x in r]
    qps = len(latencies) / window if window > 0 else 0.0

    return SearchResult(
        concurrency=point.concurrency,
        topk=point.topk,
        ef=point.ef,
        nprobe=point.nprobe,
        filter=point.filter,
        qps=qps,
        recall_at_k=recall,
        latency=summarize_latencies(latencies).as_dict(),
        measured_queries=len(latencies),
        peak_rss_mb=rss.peak_mb,
        avg_request_bytes=(sum(req_bytes) / len(req_bytes)) if req_bytes else None,
        avg_response_bytes=(sum(resp_bytes) / len(resp_bytes)) if resp_bytes else None,
    )


def run_tier(runner: Runner, scenario: Scenario, dataset: Dataset) -> TierResult:
    """Full lifecycle for one tier: setup → ingest → search grid → teardown."""
    result = TierResult(tier=runner.name)
    runner.setup(scenario.spec)
    try:
        result.ingest = measure_ingest(runner, dataset, scenario.ingest_batch)
        recall_cache: dict[tuple, float] = {}
        for point in scenario.grid.points():
            result.searches.append(
                measure_search(
                    runner,
                    dataset.queries,
                    dataset.ground_truth,
                    point,
                    recall_k=scenario.recall_k,
                    warmup_queries=scenario.warmup_queries,
                    measure_seconds=scenario.measure_seconds,
                    recall_cache=recall_cache,
                )
            )
    finally:
        runner.teardown()
    return result
