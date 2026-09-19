"""Quantization sweep: one scenario, rebuilt once per quantization variant.

For each variant (FP32 baseline, FP16, INT8, INT4, with/without rotation) the
same dataset is ingested and optimized into a fresh collection, then the
scenario's search grid is measured. The output is a side-by-side table of
recall, QPS, latency, on-disk size, optimize time and peak RSS, so the
recall-vs-size trade-off is visible at a glance.

Run the ``engine`` tier (default) to see the engine's own speed; the ``http``
tier measures the server process's RSS in isolation (the engine tier's RSS
includes the benchmark process and its in-memory dataset, which is constant
across variants, so compare deltas there).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from benchmarks import scenarios
from benchmarks.harness import measure_ingest, measure_search
from benchmarks.results import capture_env

__all__ = ["VARIANTS", "run_quant"]

# label -> (quantize_type, enable_rotate)
VARIANTS: dict[str, tuple[str | None, bool]] = {
    "fp32": (None, False),
    "fp16": ("fp16", False),
    "int8": ("int8", False),
    "int8+rot": ("int8", True),
    "int4": ("int4", False),
    "int4+rot": ("int4", True),
}


def _dir_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)


def _table(rows: list[dict[str, Any]], recall_k: int) -> str:
    """Render the sweep as a Markdown table (one row per variant x search cell)."""
    base_recall = {
        (s["concurrency"], s["ef"], s["nprobe"]): s["recall_at_k"]
        for s in rows[0]["searches"]
        if rows[0]["variant"] == "fp32"
    }
    lines = [
        f"| variant | disk MB | optimize s | peak RSS MB | c | ef | nprobe | "
        f"recall@{recall_k} | Δrecall | QPS | p50 ms | p99 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        for s in row["searches"]:
            key = (s["concurrency"], s["ef"], s["nprobe"])
            delta = s["recall_at_k"] - base_recall[key] if key in base_recall else None
            lines.append(
                f"| {row['variant']} | {row['disk_mb']:.1f} | {row['optimize_seconds']:.2f} | "
                f"{row['peak_rss_mb']:.0f} | {s['concurrency']} | {s['ef'] or '-'} | "
                f"{s['nprobe'] or '-'} | {s['recall_at_k']:.3f} | "
                f"{'-' if delta is None else f'{delta:+.3f}'} | {s['qps']:,.0f} | "
                f"{s['latency']['p50_ms']:.2f} | {s['latency']['p99_ms']:.2f} |"
            )
    return "\n".join(lines)


def run_quant(args: argparse.Namespace) -> int:
    """Entry point for ``python -m benchmarks quant``."""
    from benchmarks.cli import _build_runner

    labels = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in labels if v not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variant(s) {unknown}; choose from {list(VARIANTS)}")

    scenario = scenarios.build_scenario(args.scenario, hdf5=args.hdf5)
    if args.measure_seconds is not None:
        scenario = dataclasses.replace(scenario, measure_seconds=args.measure_seconds)
    if args.mmap is not None:
        scenario = dataclasses.replace(
            scenario, spec=dataclasses.replace(scenario.spec, enable_mmap=args.mmap)
        )

    print(f"Loading dataset for scenario '{scenario.name}' ...", flush=True)
    dataset = scenario.load()

    rows: list[dict[str, Any]] = []
    for label in labels:
        quantize_type, rotate = VARIANTS[label]
        spec = dataclasses.replace(scenario.spec, quantize_type=quantize_type, enable_rotate=rotate)
        work = Path(tempfile.mkdtemp(prefix=f"zvec-quant-{label}-"))
        runner = _build_runner(args.tier, work, args.query_threads)
        print(f"\n>>> {label} ({args.tier}) ...", flush=True)
        runner.setup(spec)
        try:
            ingest = measure_ingest(runner, dataset, scenario.ingest_batch)
            disk_mb = _dir_mb(work)
            recall_cache: dict[tuple, float] = {}
            searches = [
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
                for point in scenario.grid.points()
            ]
        finally:
            runner.teardown()
            shutil.rmtree(work, ignore_errors=True)
        row = {
            "variant": label,
            "quantize_type": quantize_type,
            "enable_rotate": rotate,
            "disk_mb": disk_mb,
            "optimize_seconds": ingest.optimize_seconds,
            "peak_rss_mb": ingest.peak_rss_mb,
            "searches": [dataclasses.asdict(s) for s in searches],
        }
        rows.append(row)
        best = max(searches, key=lambda s: s.recall_at_k)
        print(
            f"  disk {disk_mb:.1f}MB optimize {ingest.optimize_seconds:.2f}s "
            f"peak_rss {ingest.peak_rss_mb:.0f}MB best recall {best.recall_at_k:.3f}",
            flush=True,
        )

    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = capture_env(notes={"tier": args.tier}, enable_mmap=scenario.spec.enable_mmap)
    payload = {
        "scenario": scenario.name,
        "dataset": dataset.name,
        "tier": args.tier,
        "env": dataclasses.asdict(env),
        "rows": rows,
    }
    json_path = out / f"quant-{scenario.name}-{args.tier}-{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    table = _table(rows, scenario.recall_k)
    md_path = json_path.with_suffix(".md")
    md_path.write_text(
        f"# Quantization sweep — {scenario.name} ({dataset.name}), {args.tier} tier\n\n"
        f"{dataset.n:,} x {dataset.dim}, index `{scenario.spec.index}`, "
        f"mmap={scenario.spec.enable_mmap}\n\n{table}\n"
    )
    print(f"\n{table}\n\nResults written to {json_path} and {md_path}")
    return 0
