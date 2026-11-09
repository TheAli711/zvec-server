"""Quantization sweep: one scenario, rebuilt once per quantization variant.

For each variant (FP32 baseline, FP16, INT8/INT4 with/without rotation, the
zvec 0.8 uniform UINT8/UINT7/UINT4 quantizers, and product quantization) the
same dataset is ingested and optimized into a fresh collection, then the
scenario's search grid is measured. With ``--refine`` every quantized variant
is also measured with the query-time refiner (candidates re-scored against the
full-precision vectors) at each requested ``scale_factor``. The output is a
side-by-side table of recall, QPS, latency, on-disk size, optimize time and
peak RSS, so the recall-vs-size trade-off is visible at a glance.

Run the ``engine`` tier (default) to see the engine's own speed; the ``http``
tier measures the server process's RSS in isolation (the engine tier's RSS
includes the benchmark process and its in-memory dataset, which is constant
across variants, so compare deltas there).

A variant the chosen index/metric cannot build, or one a tier rejects (e.g. the
server refusing HNSW + INT8/INT4 + rotation on zvec 0.8.x), is skipped with its
reason recorded in the output instead of aborting the sweep.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks import scenarios
from benchmarks.harness import measure_ingest, measure_search
from benchmarks.results import capture_env
from benchmarks.spec import CollectionSpec

__all__ = [
    "DEFAULT_VARIANTS",
    "PQ_DIMS_PER_CHUNK",
    "VARIANTS",
    "Variant",
    "apply_variant",
    "run_quant",
    "skip_reason",
]

# Default PQ sub-vector width: ``num_chunk = dim // 4`` (32 chunks for 128-d
# SIFT, i.e. 32 B/vector at 8 bits vs 512 B for FP32). Override with --pq-chunks.
PQ_DIMS_PER_CHUNK = 4


@dataclass(frozen=True)
class Variant:
    """One quantization configuration of the vector index.

    ``indexes`` lists the index types zvec can build it on; ``l2_only`` marks
    the uniform quantizers, which only support the L2 metric.
    """

    quantize_type: str | None
    enable_rotate: bool = False
    num_bits: int | None = None  # PQ only
    fast_scan: bool = False  # PQ only (IVF + 4-bit)
    indexes: tuple[str, ...] = ("hnsw", "flat", "ivf")
    l2_only: bool = False


_PQ_INDEXES = ("hnsw", "ivf")

VARIANTS: dict[str, Variant] = {
    "fp32": Variant(None),
    "fp16": Variant("fp16"),
    "int8": Variant("int8"),
    "int8+rot": Variant("int8", enable_rotate=True),
    "int4": Variant("int4"),
    "int4+rot": Variant("int4", enable_rotate=True),
    "uint8": Variant("uniform_uint8", indexes=("hnsw",), l2_only=True),
    "uint7": Variant("uniform_uint7", indexes=("hnsw",), l2_only=True),
    "uint4": Variant("uniform_uint4", indexes=("hnsw",), l2_only=True),
    "pq": Variant("pq", num_bits=8, indexes=_PQ_INDEXES),
    "pq4": Variant("pq", num_bits=4, indexes=_PQ_INDEXES),
    "pq+opq": Variant("pq", enable_rotate=True, num_bits=8, indexes=_PQ_INDEXES),
    "pq4+fs": Variant("pq", num_bits=4, fast_scan=True, indexes=("ivf",)),
}

# Everything that builds on the shipped (HNSW, L2) scenarios.
DEFAULT_VARIANTS = tuple(k for k, v in VARIANTS.items() if "hnsw" in v.indexes)


def skip_reason(variant: Variant, spec: CollectionSpec) -> str | None:
    """Why ``variant`` cannot be built on ``spec``'s index/metric, or ``None``."""
    if spec.index not in variant.indexes:
        return f"needs index {'|'.join(variant.indexes)}, scenario uses {spec.index}"
    if variant.l2_only and spec.metric != "l2":
        return f"needs metric l2, scenario uses {spec.metric}"
    if variant.quantize_type == "pq" and spec.dtype != "VECTOR_FP32":
        return f"needs VECTOR_FP32, scenario uses {spec.dtype}"
    return None


def apply_variant(
    spec: CollectionSpec, variant: Variant, *, pq_chunks: int | None = None
) -> CollectionSpec:
    """Return ``spec`` with ``variant``'s quantization applied."""
    is_pq = variant.quantize_type == "pq"
    num_chunk = (pq_chunks or max(1, spec.dim // PQ_DIMS_PER_CHUNK)) if is_pq else None
    return dataclasses.replace(
        spec,
        quantize_type=variant.quantize_type,
        enable_rotate=variant.enable_rotate,
        num_chunk=num_chunk,
        num_bits=variant.num_bits,
        fast_scan=variant.fast_scan,
    )


def _dir_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)


def _fmt_refine(refine: float | None) -> str:
    return "-" if refine is None else f"{refine:g}"


def _table(rows: list[dict[str, Any]], recall_k: int) -> str:
    """Render the sweep as a Markdown table (one row per variant x search cell).

    Δrecall compares each cell to the FP32 cell with the same (c, ef, nprobe),
    refined or not, so it shows what quantization (+ refiner) costs vs FP32.
    """
    base_recall = {
        (s["concurrency"], s["ef"], s["nprobe"]): s["recall_at_k"]
        for row in rows
        if row["variant"] == "fp32"
        for s in row["searches"]
        if s.get("refine") is None
    }
    lines = [
        f"| variant | disk MB | optimize s | peak RSS MB | c | ef | nprobe | refine | "
        f"recall@{recall_k} | Δrecall | QPS | p50 ms | p99 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        for s in row["searches"]:
            key = (s["concurrency"], s["ef"], s["nprobe"])
            delta = s["recall_at_k"] - base_recall[key] if key in base_recall else None
            lines.append(
                f"| {row['variant']} | {row['disk_mb']:.1f} | {row['optimize_seconds']:.2f} | "
                f"{row['peak_rss_mb']:.0f} | {s['concurrency']} | {s['ef'] or '-'} | "
                f"{s['nprobe'] or '-'} | {_fmt_refine(s.get('refine'))} | "
                f"{s['recall_at_k']:.3f} | {'-' if delta is None else f'{delta:+.3f}'} | "
                f"{s['qps']:,.0f} | {s['latency']['p50_ms']:.2f} | {s['latency']['p99_ms']:.2f} |"
            )
    return "\n".join(lines)


def _skipped_md(skipped: list[dict[str, str]]) -> str:
    if not skipped:
        return ""
    items = "\n".join(f"- `{s['variant']}`{s.get('cell', '')}: {s['reason']}" for s in skipped)
    return f"\n\n**Skipped:**\n\n{items}\n"


def _parse_floats(text: str | None) -> tuple[float, ...]:
    return tuple(float(x) for x in (text or "").split(",") if x.strip())


def _parse_ints(text: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in (text or "").split(",") if x.strip())


def _scenario_for(args: argparse.Namespace) -> scenarios.Scenario:
    """Resolve the scenario and apply the CLI's spec/grid overrides."""
    scenario = scenarios.build_scenario(args.scenario, hdf5=args.hdf5)
    spec, grid = scenario.spec, scenario.grid
    if args.mmap is not None:
        spec = dataclasses.replace(spec, enable_mmap=args.mmap)
    if args.index is not None and args.index != spec.index:
        spec = dataclasses.replace(spec, index=args.index)
        # ef only applies to HNSW; let the IVF engine default stand unless swept.
        grid = dataclasses.replace(grid, ef=(None,) if args.index != "hnsw" else grid.ef)
    if ef := _parse_ints(args.ef):
        grid = dataclasses.replace(grid, ef=ef)
    if nprobe := _parse_ints(args.nprobe):
        grid = dataclasses.replace(grid, nprobe=nprobe)
    if conc := _parse_ints(args.concurrency):
        grid = dataclasses.replace(grid, concurrency=conc)
    scenario = dataclasses.replace(scenario, spec=spec, grid=grid)
    if args.measure_seconds is not None:
        scenario = dataclasses.replace(scenario, measure_seconds=args.measure_seconds)
    return scenario


def run_quant(args: argparse.Namespace) -> int:
    """Entry point for ``python -m benchmarks quant``."""
    from benchmarks.cli import _build_runner

    labels = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in labels if v not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variant(s) {unknown}; choose from {list(VARIANTS)}")
    refine = _parse_floats(args.refine)

    scenario = _scenario_for(args)
    print(f"Loading dataset for scenario '{scenario.name}' ...", flush=True)
    dataset = scenario.load()

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for label in labels:
        variant = VARIANTS[label]
        if reason := skip_reason(variant, scenario.spec):
            print(f"\n>>> {label}: skipped ({reason})", flush=True)
            skipped.append({"variant": label, "reason": reason})
            continue
        spec = apply_variant(scenario.spec, variant, pq_chunks=args.pq_chunks)
        # The refiner re-scores quantized candidates; it is meaningless (and
        # raises on zvec 0.8.1 HNSW) without quantization, so FP32 never gets it.
        grid = scenario.grid
        if refine and variant.quantize_type is not None:
            grid = dataclasses.replace(grid, refine=(None, *refine))
        work = Path(tempfile.mkdtemp(prefix=f"zvec-quant-{label}-"))
        runner = _build_runner(args.tier, work, args.query_threads)
        print(f"\n>>> {label} ({args.tier}) {spec.index_params()} ...", flush=True)
        searches = []
        try:
            runner.setup(spec)
            ingest = measure_ingest(runner, dataset, scenario.ingest_batch)
            disk_mb = _dir_mb(work)
            recall_cache: dict[tuple, float] = {}
            for point in grid.points():
                try:
                    searches.append(
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
                except Exception as exc:
                    cell = f" (c={point.concurrency} ef={point.ef} refine={point.refine})"
                    print(f"  cell{cell} failed: {exc}", flush=True)
                    skipped.append({"variant": label, "cell": cell, "reason": str(exc)[:300]})
        except Exception as exc:
            print(f"  {label} failed, skipping: {exc}", flush=True)
            skipped.append({"variant": label, "reason": str(exc)[:300]})
            continue
        finally:
            runner.teardown()
            shutil.rmtree(work, ignore_errors=True)
        row = {
            "variant": label,
            "quantize_type": spec.quantize_type,
            "enable_rotate": spec.enable_rotate,
            "index_params": spec.index_params(),
            "disk_mb": disk_mb,
            "ingest_seconds": ingest.seconds,
            "optimize_seconds": ingest.optimize_seconds,
            "peak_rss_mb": ingest.peak_rss_mb,
            "searches": [dataclasses.asdict(s) for s in searches],
        }
        rows.append(row)
        best = max((s.recall_at_k for s in searches), default=float("nan"))
        print(
            f"  disk {disk_mb:.1f}MB ingest {ingest.seconds:.1f}s "
            f"optimize {ingest.optimize_seconds:.2f}s peak_rss {ingest.peak_rss_mb:.0f}MB "
            f"best recall {best:.3f}",
            flush=True,
        )

    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = capture_env(
        notes={"tier": args.tier, "refine": list(refine)},
        zvec_query_threads=args.query_threads,
        enable_mmap=scenario.spec.enable_mmap,
    )
    payload = {
        "scenario": scenario.name,
        "dataset": dataset.name,
        "tier": args.tier,
        "spec": dataclasses.asdict(scenario.spec),
        "env": dataclasses.asdict(env),
        "rows": rows,
        "skipped": skipped,
    }
    json_path = out / f"quant-{scenario.name}-{args.tier}-{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    table = _table(rows, scenario.recall_k)
    md_path = json_path.with_suffix(".md")
    md_path.write_text(
        f"# Quantization sweep — {scenario.name} ({dataset.name}), {args.tier} tier\n\n"
        f"{dataset.n:,} x {dataset.dim}, index `{scenario.spec.index}`, "
        f"mmap={scenario.spec.enable_mmap}, zvec {env.zvec_version}\n\n"
        f"{table}\n{_skipped_md(skipped)}"
    )
    print(f"\n{table}\n{_skipped_md(skipped)}\nResults written to {json_path} and {md_path}")
    return 0
