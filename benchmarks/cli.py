"""Command-line entry point: ``python -m benchmarks run --scenario <name>``.

Orchestrates a run: resolve the scenario, load the dataset (+ ground truth),
capture the environment, then drive each requested tier through the harness and
write a result JSON. A compact summary is printed to stdout; the richer markdown
report + plots are produced by :mod:`benchmarks.report` when available.
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
import sys
import tempfile
from pathlib import Path

from benchmarks import scenarios
from benchmarks.harness import run_tier
from benchmarks.results import RunResult, TierResult, capture_env
from benchmarks.runners.base import Runner

DEFAULT_OUT = Path(__file__).resolve().parent / "results"
ALL_TIERS = ("engine", "inproc", "http")


def _build_runner(tier: str, data_dir: Path, query_threads: int | None) -> Runner:
    """Construct a runner, importing its module lazily so one bad tier can't
    break the others."""
    if tier == "engine":
        from benchmarks.runners.engine import EngineRunner

        return EngineRunner(data_dir, query_threads=query_threads)
    if tier == "inproc":
        from benchmarks.runners.inproc import InprocRunner

        return InprocRunner(data_dir, query_threads=query_threads)
    if tier == "http":
        from benchmarks.runners.http import HttpRunner

        return HttpRunner(data_dir, query_threads=query_threads)
    raise ValueError(f"unknown tier {tier!r}; choose from {ALL_TIERS}")


def _print_summary(result: RunResult) -> None:
    print(f"\n=== {result.scenario} ({result.dataset}) ===")
    for tier in result.tiers:
        ing = tier.ingest
        if ing is not None:
            print(
                f"[{tier.tier}] ingest: {ing.docs_per_sec:,.0f} docs/s "
                f"({ing.seconds:.1f}s) optimize {ing.optimize_seconds:.1f}s "
                f"peak_rss {ing.peak_rss_mb:.0f}MB"
            )
        for s in tier.searches:
            bytes_note = ""
            if s.avg_request_bytes:
                resp_b = s.avg_response_bytes or 0
                bytes_note = f" req~{s.avg_request_bytes:,.0f}B resp~{resp_b:,.0f}B"
            print(
                f"[{tier.tier}] c={s.concurrency:<2} ef={s.ef} topk={s.topk} "
                f"qps={s.qps:8,.0f} recall@{result.spec.get('recall_k', '')}"
                f"={s.recall_at_k:.3f} p50={s.latency['p50_ms']:.2f}ms "
                f"p99={s.latency['p99_ms']:.2f}ms{bytes_note}"
            )


def _decomposition(result: RunResult) -> None:
    """Print the headline engine→inproc→http latency tax for shared grid cells."""
    by_tier = {t.tier: t for t in result.tiers}
    if "engine" not in by_tier:
        return

    def cell_key(s: object) -> tuple:
        return (s.topk, s.ef, s.nprobe, s.filter, s.concurrency)  # type: ignore[attr-defined]

    eng = {cell_key(s): s for s in by_tier["engine"].searches}
    print("\n--- overhead decomposition (p50 ms) ---")
    print(f"{'cell':<22}{'engine':>9}{'inproc':>9}{'http':>9}{'Δlogic':>9}{'Δtransport':>12}")
    for key, e in eng.items():
        ip = next(
            (s for s in by_tier.get("inproc", TierResult("")).searches if cell_key(s) == key), None
        )
        ht = next(
            (s for s in by_tier.get("http", TierResult("")).searches if cell_key(s) == key), None
        )
        e_p = e.latency["p50_ms"]
        ip_p = ip.latency["p50_ms"] if ip else None
        ht_p = ht.latency["p50_ms"] if ht else None
        d_logic = f"{ip_p - e_p:+.2f}" if ip_p is not None else "-"
        d_tx = f"{ht_p - ip_p:+.2f}" if (ht_p is not None and ip_p is not None) else "-"
        label = f"c{key[4]} ef{key[1]} k{key[0]}"
        print(
            f"{label:<22}{e_p:>9.2f}"
            f"{(ip_p if ip_p is not None else float('nan')):>9.2f}"
            f"{(ht_p if ht_p is not None else float('nan')):>9.2f}"
            f"{d_logic:>9}{d_tx:>12}"
        )


def run(args: argparse.Namespace) -> int:
    scenario = scenarios.build_scenario(args.scenario, hdf5=args.hdf5)
    if args.measure_seconds is not None:
        scenario = scenarios.Scenario(
            **{**scenario.__dict__, "measure_seconds": args.measure_seconds}
        )
    if args.mmap is not None:
        spec = dataclasses.replace(scenario.spec, enable_mmap=args.mmap)
        scenario = scenarios.Scenario(**{**scenario.__dict__, "spec": spec})

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    print(f"Loading dataset for scenario '{scenario.name}' ...", flush=True)
    dataset = scenario.load()
    print(
        f"  {dataset.name}: {dataset.n:,} x {dataset.dim} ({dataset.metric}), "
        f"{dataset.queries.shape[0]} queries",
        flush=True,
    )

    env = capture_env(
        notes={"tiers": tiers, "loopback": True},
        zvec_query_threads=args.query_threads,
        enable_mmap=scenario.spec.enable_mmap,
    )
    result = RunResult(
        scenario=scenario.name,
        dataset=dataset.name,
        spec={**scenario.spec.__dict__, "recall_k": scenario.recall_k},
        env=env,
    )

    work_root = Path(tempfile.mkdtemp(prefix="zvec-bench-"))
    try:
        for tier in tiers:
            print(f"\n>>> running tier '{tier}' ...", flush=True)
            data_dir = work_root / tier
            runner = _build_runner(tier, data_dir, args.query_threads)
            result.tiers.append(run_tier(runner, scenario, dataset))
    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    out_dir = Path(args.out)
    path = result.save(out_dir)
    _print_summary(result)
    _decomposition(result)
    print(f"\nResults written to {path}")

    try:
        from benchmarks.report import write_report

        report_path = write_report(path)
        print(f"Report written to {report_path}")
    except Exception as exc:  # report is optional / may still be in progress
        print(f"(report generation skipped: {exc})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmarks", description="Zvec Server benchmarks")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a scenario across tiers")
    run_p.add_argument("--scenario", default="smoke", help=f"one of {scenarios.SCENARIO_NAMES}")
    run_p.add_argument(
        "--tiers", default=",".join(ALL_TIERS), help="comma-separated subset of engine,inproc,http"
    )
    run_p.add_argument("--hdf5", default=None, help="ann-benchmarks HDF5 path (cohere scenarios)")
    run_p.add_argument("--out", default=str(DEFAULT_OUT), help="results output directory")
    run_p.add_argument("--query-threads", type=int, default=None, help="ZVEC query thread count")
    run_p.add_argument(
        "--mmap",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable mmap storage (production parity); default off for clean recall",
    )
    run_p.add_argument(
        "--measure-seconds", type=float, default=None, help="override per-cell measurement window"
    )
    run_p.set_defaults(func=run)

    list_p = sub.add_parser("list", help="list available scenarios")
    list_p.set_defaults(func=lambda _a: (print("\n".join(scenarios.SCENARIO_NAMES)), 0)[1])

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
