"""Search latency while ``optimize`` runs.

Ingests a scenario's corpus *without* optimizing, measures a baseline search
window, then triggers optimize and keeps searching at a fixed concurrency until
it finishes. Comparing the two windows shows whether optimize blocks reads: if
it holds an exclusive lock, queries stall for the whole optimize (max latency ≈
optimize duration, QPS collapses); if reads may proceed, latency stays close to
the baseline.

Use the ``inproc`` or ``http`` tier — they go through the server's
``CollectionManager`` locking. ``engine`` has no server locks and serves as a
control for the engine's own behaviour.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from benchmarks import scenarios
from benchmarks.metrics import summarize_latencies
from benchmarks.results import capture_env
from benchmarks.runners.base import Runner

__all__ = ["run_optimize_load", "search_until"]


def search_until(
    runner: Runner,
    queries: np.ndarray,
    *,
    concurrency: int,
    topk: int,
    ef: int | None,
    stop: threading.Event,
) -> tuple[list[float], float]:
    """Run closed-loop searches until ``stop`` is set; return (latencies_s, window_s)."""
    counter = itertools.count()
    n_q = queries.shape[0]

    def worker() -> list[float]:
        lat: list[float] = []
        while not stop.is_set():
            i = next(counter) % n_q
            t0 = time.perf_counter()
            runner.search(queries[i], topk, ef=ef)
            lat.append(time.perf_counter() - t0)
        return lat

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _: worker(), range(concurrency)))
    return [x for lat in results for x in lat], time.perf_counter() - start


def _window(latencies: list[float], seconds: float) -> dict[str, Any]:
    stats = summarize_latencies(latencies).as_dict() if latencies else {}
    return {
        "seconds": seconds,
        "queries": len(latencies),
        "qps": len(latencies) / seconds if seconds > 0 else 0.0,
        "latency": stats,
        "max_ms": max(latencies) * 1000 if latencies else None,
    }


def run_optimize_load(args: argparse.Namespace) -> int:
    """Entry point for ``python -m benchmarks optimize-load``."""
    from benchmarks.cli import _build_runner

    scenario = scenarios.build_scenario(args.scenario, hdf5=args.hdf5)
    spec = scenario.spec
    if args.mmap is not None:
        spec = dataclasses.replace(spec, enable_mmap=args.mmap)
    ef = args.ef if args.ef is not None else next(e for e in scenario.grid.ef if e is not None)

    print(f"Loading dataset for scenario '{scenario.name}' ...", flush=True)
    dataset = scenario.load()
    work = Path(tempfile.mkdtemp(prefix="zvec-optload-"))
    runner = _build_runner(args.tier, work, args.query_threads)
    runner.setup(spec)
    try:
        ids, vectors = dataset.doc_ids(), dataset.train
        for start in range(0, dataset.n, scenario.ingest_batch):
            end = min(start + scenario.ingest_batch, dataset.n)
            runner.ingest(ids[start:end], vectors[start:end], None)
        print(f"  ingested {dataset.n:,} docs (not optimized)", flush=True)

        # Baseline: same (unoptimized) collection, no optimize running.
        stop = threading.Event()
        timer = threading.Timer(args.baseline_seconds, stop.set)
        timer.start()
        base_lat, base_s = search_until(
            runner, dataset.queries, concurrency=args.concurrency, topk=10, ef=ef, stop=stop
        )

        # Under load: searches run until optimize returns.
        stop = threading.Event()
        optimize_s: list[float] = []

        def _optimize() -> None:
            t0 = time.perf_counter()
            try:
                runner.optimize()
            finally:
                optimize_s.append(time.perf_counter() - t0)
                stop.set()

        opt = threading.Thread(target=_optimize)
        opt.start()
        load_lat, load_s = search_until(
            runner, dataset.queries, concurrency=args.concurrency, topk=10, ef=ef, stop=stop
        )
        opt.join()
    finally:
        runner.teardown()
        shutil.rmtree(work, ignore_errors=True)

    baseline, during = _window(base_lat, base_s), _window(load_lat, load_s)
    result = {
        "scenario": scenario.name,
        "tier": args.tier,
        "concurrency": args.concurrency,
        "ef": ef,
        "optimize_seconds": optimize_s[0] if optimize_s else None,
        "baseline": baseline,
        "during_optimize": during,
        "env": dataclasses.asdict(
            capture_env(notes={"tier": args.tier}, enable_mmap=spec.enable_mmap)
        ),
    }

    def _row(label: str, w: dict[str, Any]) -> str:
        lat = w["latency"]
        return (
            f"| {label} | {w['seconds']:.2f} | {w['queries']:,} | {w['qps']:,.0f} | "
            f"{lat.get('p50_ms', float('nan')):.2f} | {lat.get('p99_ms', float('nan')):.2f} | "
            f"{(w['max_ms'] or float('nan')):.1f} |"
        )

    table = "\n".join(
        [
            "| window | seconds | queries | QPS | p50 ms | p99 ms | max ms |",
            "|---|---:|---:|---:|---:|---:|---:|",
            _row("baseline", baseline),
            _row("during optimize", during),
        ]
    )
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"optimize-load-{scenario.name}-{args.tier}-{stamp}.json"
    json_path.write_text(json.dumps(result, indent=2, default=str))
    header = (
        f"optimize-load — {scenario.name}, {args.tier} tier, c={args.concurrency}, ef={ef}; "
        f"optimize took {result['optimize_seconds']:.2f}s"
    )
    json_path.with_suffix(".md").write_text(f"# {header}\n\n{table}\n")
    print(f"\n{header}\n\n{table}\n\nResults written to {json_path}")
    return 0
