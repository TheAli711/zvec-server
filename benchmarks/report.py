"""Turn a benchmark result JSON into a markdown report plus matplotlib plots.

The result schema lives in :mod:`benchmarks.results` (we import it so this
module tracks the canonical location), but we read the JSON as nested dicts —
that is simpler and tolerant of missing/``None`` fields produced by partial
runs.

Public entry point:

* :func:`write_report` — render ``report.md`` next to the result JSON (or in a
  caller-supplied directory) and emit PNG plots under ``<dir>/plots/``.

CLI: ``python -m benchmarks.report <result.json> [out_dir]``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless: must precede pyplot import.
import matplotlib.pyplot as plt

# Imported for the schema dependency (and so a refactor there flags here).
from benchmarks import results as _results  # noqa: F401

__all__ = ["write_report"]

# Tier display order, regardless of order in the JSON.
TIER_ORDER = ("engine", "inproc", "http")

# A grid cell is uniquely identified by these axes (``include_vector`` is not
# carried on SearchResult, so it cannot participate in matching).
_CELL_KEYS = ("topk", "ef", "nprobe", "concurrency", "filter")

Cell = tuple[Any, ...]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _fmt(value: Any, digits: int = 2) -> str:
    """Render a number with fixed precision, or ``-`` for ``None``."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a GitHub-flavoured markdown table."""
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return "\n".join([head, sep, body]) if rows else head + "\n" + sep


def _cell_key(search: dict[str, Any]) -> Cell:
    """The matching key for a search result across tiers."""
    return tuple(search.get(k) for k in _CELL_KEYS)


def _latency(search: dict[str, Any], stat: str) -> float | None:
    """Pull a latency percentile (e.g. ``p50_ms``) from a search dict."""
    lat = search.get("latency") or {}
    val = lat.get(stat)
    return float(val) if val is not None else None


def _tiers_by_name(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the run's tiers by their ``tier`` name."""
    return {t.get("tier", ""): t for t in result.get("tiers", [])}


def _ordered_tiers(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return tiers in canonical order, ignoring unknown names' position."""
    by_name = _tiers_by_name(result)
    known = [by_name[name] for name in TIER_ORDER if name in by_name]
    extra = [t for n, t in by_name.items() if n not in TIER_ORDER]
    return known + extra


def _searches_by_cell(tier: dict[str, Any]) -> dict[Cell, dict[str, Any]]:
    """Map each grid cell to its (last-wins) search result for one tier."""
    return {_cell_key(s): s for s in tier.get("searches", [])}


# --------------------------------------------------------------------------- #
# Markdown sections
# --------------------------------------------------------------------------- #
def _env_section(env: dict[str, Any]) -> str:
    """Environment table from the run's :class:`EnvInfo`."""
    fields = [
        ("timestamp", "Timestamp"),
        ("hostname", "Hostname"),
        ("platform", "Platform"),
        ("python_version", "Python"),
        ("zvec_version", "Zvec"),
        ("git_commit", "Git commit"),
        ("cpu_model", "CPU"),
        ("cpu_physical", "CPU physical cores"),
        ("cpu_logical", "CPU logical cores"),
        ("ram_gb", "RAM (GB)"),
        ("zvec_query_threads", "Zvec query threads"),
        ("anyio_threadpool", "AnyIO threadpool"),
        ("enable_mmap", "mmap enabled"),
    ]
    rows = [[label, _fmt(env.get(key))] for key, label in fields if env.get(key) is not None]
    notes = env.get("notes") or {}
    if notes:
        rows.append(["notes", ", ".join(f"{k}={v}" for k, v in notes.items())])
    return "## Environment\n\n" + _md_table(["Field", "Value"], rows)


def _scenario_line(result: dict[str, Any]) -> str:
    """One-line dataset + spec summary."""
    spec = result.get("spec") or {}
    parts = []
    for key in ("dim", "dtype", "index", "metric", "m", "ef_construction", "n_list", "n_iters"):
        val = spec.get(key)
        if val is not None:
            parts.append(f"{key}={val}")
    spec_str = ", ".join(parts) if parts else "n/a"
    dataset = result.get("dataset", "?")
    scenario = result.get("scenario", "?")
    return f"**Scenario:** `{scenario}` &nbsp; **Dataset:** `{dataset}`\n\n**Spec:** {spec_str}"


def _ingest_section(result: dict[str, Any]) -> str:
    """Ingest table — one row per tier."""
    headers = [
        "Tier",
        "n_docs",
        "docs/sec",
        "ingest (s)",
        "optimize (s)",
        "peak RSS (MB)",
    ]
    rows: list[list[str]] = []
    for tier in _ordered_tiers(result):
        ing = tier.get("ingest")
        if not ing:
            continue
        rows.append(
            [
                tier.get("tier", "?"),
                _fmt(ing.get("n_docs")),
                _fmt(ing.get("docs_per_sec")),
                _fmt(ing.get("seconds")),
                _fmt(ing.get("optimize_seconds")),
                _fmt(ing.get("peak_rss_mb")),
            ]
        )
    if not rows:
        return "## Ingest\n\n_No ingest data._"
    return "## Ingest\n\n" + _md_table(headers, rows)


def _search_section(result: dict[str, Any]) -> str:
    """Per-tier search tables."""
    blocks = ["## Search"]
    for tier in _ordered_tiers(result):
        name = tier.get("tier", "?")
        searches = tier.get("searches") or []
        if not searches:
            continue
        is_http = name == "http"
        headers = ["concurrency", "ef", "topk", "filter", "qps", "recall@k", "p50 (ms)", "p99 (ms)"]
        headers.append("peak RSS (MB)")
        if is_http:
            headers += ["req bytes", "resp bytes"]
        rows: list[list[str]] = []
        for s in sorted(searches, key=lambda x: (x.get("concurrency") or 0, x.get("ef") or 0)):
            row = [
                _fmt(s.get("concurrency")),
                _fmt(s.get("ef")),
                _fmt(s.get("topk")),
                str(s.get("filter") or "-"),
                _fmt(s.get("qps")),
                _fmt(s.get("recall_at_k"), 4),
                _fmt(_latency(s, "p50_ms")),
                _fmt(_latency(s, "p99_ms")),
                _fmt(s.get("peak_rss_mb")),
            ]
            if is_http:
                row += [_fmt(s.get("avg_request_bytes")), _fmt(s.get("avg_response_bytes"))]
            rows.append(row)
        blocks.append(f"### Tier: `{name}`\n\n" + _md_table(headers, rows))
    return "\n\n".join(blocks)


def _overhead_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute overhead-decomposition records across tiers, per grid cell.

    Each record carries the per-tier p50/qps and the two deltas. Cells are
    those present in at least one tier; deltas are ``None`` when an endpoint of
    the subtraction is missing.
    """
    by_name = _tiers_by_name(result)
    per_tier = {name: _searches_by_cell(by_name[name]) for name in by_name}
    all_cells: set[Cell] = set()
    for cells in per_tier.values():
        all_cells.update(cells)

    records: list[dict[str, Any]] = []
    for cell in sorted(all_cells, key=lambda c: tuple(-1 if v is None else v for v in c[:4])):
        rec: dict[str, Any] = dict(zip(_CELL_KEYS, cell, strict=True))
        eng = per_tier.get("engine", {}).get(cell)
        inp = per_tier.get("inproc", {}).get(cell)
        htp = per_tier.get("http", {}).get(cell)
        rec["engine_p50"] = _latency(eng, "p50_ms") if eng else None
        rec["inproc_p50"] = _latency(inp, "p50_ms") if inp else None
        rec["http_p50"] = _latency(htp, "p50_ms") if htp else None
        rec["engine_qps"] = eng.get("qps") if eng else None
        rec["inproc_qps"] = inp.get("qps") if inp else None
        rec["http_qps"] = htp.get("qps") if htp else None
        rec["d_logic"] = (
            rec["inproc_p50"] - rec["engine_p50"]
            if rec["inproc_p50"] is not None and rec["engine_p50"] is not None
            else None
        )
        rec["d_transport"] = (
            rec["http_p50"] - rec["inproc_p50"]
            if rec["http_p50"] is not None and rec["inproc_p50"] is not None
            else None
        )
        records.append(rec)
    return records


def _overhead_section(records: list[dict[str, Any]]) -> str:
    """The headline overhead-decomposition table."""
    if not records:
        return "## Overhead decomposition\n\n_No overlapping grid cells._"
    headers = [
        "concurrency",
        "ef",
        "topk",
        "filter",
        "engine p50",
        "inproc p50",
        "http p50",
        "engine qps",
        "inproc qps",
        "http qps",
        "Δ_logic_ms",
        "Δ_transport_ms",
    ]
    rows: list[list[str]] = []
    for r in records:
        rows.append(
            [
                _fmt(r["concurrency"]),
                _fmt(r["ef"]),
                _fmt(r["topk"]),
                str(r["filter"] or "-"),
                _fmt(r["engine_p50"]),
                _fmt(r["inproc_p50"]),
                _fmt(r["http_p50"]),
                _fmt(r["engine_qps"]),
                _fmt(r["inproc_qps"]),
                _fmt(r["http_qps"]),
                _fmt(r["d_logic"]),
                _fmt(r["d_transport"]),
            ]
        )
    intro = (
        "Per matching grid cell across tiers. `Δ_logic_ms` is the server-logic "
        "cost (inproc - engine); `Δ_transport_ms` is the HTTP/JSON boundary "
        "cost (http - inproc)."
    )
    return "## Overhead decomposition\n\n" + intro + "\n\n" + _md_table(headers, rows)


def _payload_section(result: dict[str, Any]) -> str:
    """A short note on the JSON tax for HTTP request payloads."""
    http = _tiers_by_name(result).get("http")
    if not http:
        return ""
    sizes = [
        s.get("avg_request_bytes")
        for s in http.get("searches") or []
        if s.get("avg_request_bytes") is not None
    ]
    if not sizes:
        return ""
    dim = (result.get("spec") or {}).get("dim")
    avg_req = sum(sizes) / len(sizes)
    lines = ["## Payload", ""]
    if dim:
        raw = dim * 4  # fp32 query vector.
        tax = avg_req / raw if raw else float("nan")
        lines.append(
            f"A raw fp32 query vector is `{dim} x 4 = {raw} bytes`, but the average "
            f"HTTP search request is `{avg_req:.0f} bytes` "
            f"(~**{tax:.1f}x** the raw vector) -- the JSON encoding tax."
        )
    else:
        lines.append(f"Average HTTP search request: `{avg_req:.0f} bytes`.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Plots
# --------------------------------------------------------------------------- #
def _save(fig: plt.Figure, path: Path) -> None:
    """Persist and close a figure."""
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _plot_qps_vs_recall(result: dict[str, Any], plots_dir: Path) -> str | None:
    """QPS vs recall@k across the ef sweep, one line per tier (max concurrency)."""
    tiers = _ordered_tiers(result)
    concs = {
        s.get("concurrency")
        for t in tiers
        for s in t.get("searches") or []
        if s.get("concurrency") is not None
    }
    if not concs:
        return None
    conc = max(concs)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    drawn = 0
    for tier in tiers:
        pts = [
            s
            for s in tier.get("searches") or []
            if s.get("concurrency") == conc and s.get("recall_at_k") is not None
        ]
        pts.sort(key=lambda s: s.get("ef") or 0)
        xs = [s.get("recall_at_k") for s in pts]
        ys = [s.get("qps") for s in pts]
        if len([y for y in ys if y is not None]) >= 1:
            ax.plot(xs, ys, marker="o", label=tier.get("tier", "?"))
            drawn += 1
    if drawn < 1:
        plt.close(fig)
        return None
    ax.set_xlabel("recall@k")
    ax.set_ylabel("QPS")
    ax.set_title(f"QPS vs recall (concurrency={conc})")
    ax.grid(True, alpha=0.3)
    ax.legend()
    name = "qps_vs_recall.png"
    _save(fig, plots_dir / name)
    return name


def _plot_latency_percentiles(result: dict[str, Any], plots_dir: Path) -> str | None:
    """Percentile curve (p50/p90/p95/p99) per tier for a representative cell."""
    tiers = _ordered_tiers(result)
    concs = {
        s.get("concurrency")
        for t in tiers
        for s in t.get("searches") or []
        if s.get("concurrency") is not None
    }
    if not concs:
        return None
    conc = max(concs)
    efs = sorted(
        {
            s.get("ef")
            for t in tiers
            for s in t.get("searches") or []
            if s.get("concurrency") == conc and s.get("ef") is not None
        }
    )
    ef = efs[len(efs) // 2] if efs else None  # mid ef.
    pcts = [50, 90, 95, 99]
    stats = ["p50_ms", "p90_ms", "p95_ms", "p99_ms"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    drawn = 0
    for tier in tiers:
        match = [
            s
            for s in tier.get("searches") or []
            if s.get("concurrency") == conc and s.get("ef") == ef
        ]
        if not match:
            continue
        s = match[0]
        ys = [_latency(s, stat) for stat in stats]
        if any(y is not None for y in ys):
            ax.plot(pcts, ys, marker="o", label=tier.get("tier", "?"))
            drawn += 1
    if drawn < 1:
        plt.close(fig)
        return None
    ax.set_xlabel("percentile")
    ax.set_ylabel("latency (ms)")
    title_ef = f", ef={ef}" if ef is not None else ""
    ax.set_title(f"latency percentiles (concurrency={conc}{title_ef})")
    ax.set_xticks(pcts)
    ax.grid(True, alpha=0.3)
    ax.legend()
    name = "latency_cdf.png"
    _save(fig, plots_dir / name)
    return name


def _plot_qps_vs_concurrency(result: dict[str, Any], plots_dir: Path) -> str | None:
    """QPS vs concurrency, one line per tier (fix ef/topk to a representative)."""
    tiers = _ordered_tiers(result)
    efs = sorted(
        {s.get("ef") for t in tiers for s in t.get("searches") or [] if s.get("ef") is not None}
    )
    ef = efs[len(efs) // 2] if efs else None  # mid ef.
    fig, ax = plt.subplots(figsize=(7, 4.5))
    drawn = 0
    for tier in tiers:
        pts = [s for s in tier.get("searches") or [] if s.get("ef") == ef]
        pts.sort(key=lambda s: s.get("concurrency") or 0)
        xs = [s.get("concurrency") for s in pts]
        ys = [s.get("qps") for s in pts]
        if len([y for y in ys if y is not None]) >= 1:
            ax.plot(xs, ys, marker="o", label=tier.get("tier", "?"))
            drawn += 1
    if drawn < 1:
        plt.close(fig)
        return None
    ax.set_xlabel("concurrency")
    ax.set_ylabel("QPS")
    title_ef = f" (ef={ef})" if ef is not None else ""
    ax.set_title(f"QPS vs concurrency{title_ef}")
    ax.grid(True, alpha=0.3)
    ax.legend()
    name = "qps_vs_concurrency.png"
    _save(fig, plots_dir / name)
    return name


def _plot_latency_breakdown(records: list[dict[str, Any]], plots_dir: Path) -> str | None:
    """Stacked bars per concurrency: engine p50, Δ_logic, Δ_transport."""
    usable = [
        r
        for r in records
        if r["engine_p50"] is not None
        and (r["d_logic"] is not None or r["d_transport"] is not None)
    ]
    if not usable:
        return None
    # Pick one representative ef (mid) so each concurrency yields one bar.
    efs = sorted({r["ef"] for r in usable if r["ef"] is not None})
    ef = efs[len(efs) // 2] if efs else None
    bars = [r for r in usable if r["ef"] == ef] if ef is not None else usable
    bars.sort(key=lambda r: r["concurrency"] or 0)
    if not bars:
        return None
    labels = [str(r["concurrency"]) for r in bars]
    engine = [r["engine_p50"] or 0.0 for r in bars]
    logic = [r["d_logic"] or 0.0 for r in bars]
    transport = [r["d_transport"] or 0.0 for r in bars]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bottom_logic = engine
    bottom_transport = [e + lg for e, lg in zip(engine, logic, strict=True)]
    ax.bar(labels, engine, label="engine p50")
    ax.bar(labels, logic, bottom=bottom_logic, label="Δ_logic")
    ax.bar(labels, transport, bottom=bottom_transport, label="Δ_transport")
    ax.set_xlabel("concurrency")
    ax.set_ylabel("p50 latency (ms)")
    title_ef = f" (ef={ef})" if ef is not None else ""
    ax.set_title(f"latency breakdown{title_ef}")
    ax.legend()
    name = "latency_breakdown.png"
    _save(fig, plots_dir / name)
    return name


def _generate_plots(
    result: dict[str, Any], records: list[dict[str, Any]], plots_dir: Path
) -> dict[str, str | None]:
    """Generate all supported plots; returns ``{logical_name: filename|None}``."""
    plots_dir.mkdir(parents=True, exist_ok=True)
    return {
        "qps_vs_recall": _plot_qps_vs_recall(result, plots_dir),
        "latency_cdf": _plot_latency_percentiles(result, plots_dir),
        "qps_vs_concurrency": _plot_qps_vs_concurrency(result, plots_dir),
        "latency_breakdown": _plot_latency_breakdown(records, plots_dir),
    }


def _plots_section(plots: dict[str, str | None]) -> str:
    """Embed produced plots with relative paths; skip the missing ones."""
    titles = {
        "qps_vs_recall": "QPS vs recall",
        "latency_cdf": "Latency percentiles",
        "qps_vs_concurrency": "QPS vs concurrency",
        "latency_breakdown": "Latency breakdown",
    }
    blocks = ["## Plots"]
    for key, title in titles.items():
        fname = plots.get(key)
        if fname:
            blocks.append(f"### {title}\n\n![{title}](plots/{fname})")
    if len(blocks) == 1:
        return ""
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def write_report(result_path: Path, out_dir: Path | None = None) -> Path:
    """Render a markdown report and plots from a benchmark result JSON.

    Args:
        result_path: Path to a JSON produced by ``RunResult.to_json()``.
        out_dir: Destination directory; defaults to the JSON's directory. The
            report is written as ``report.md`` with plots under ``plots/``.

    Returns:
        The path to the written ``report.md``.
    """
    result_path = Path(result_path)
    result: dict[str, Any] = json.loads(result_path.read_text())

    out_dir = Path(out_dir) if out_dir is not None else result_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = out_dir / "plots"

    records = _overhead_rows(result)
    plots = _generate_plots(result, records, plots_dir)

    scenario = result.get("scenario", "?")
    sections = [
        f"# Benchmark report — `{scenario}`",
        _env_section(result.get("env") or {}),
        _scenario_line(result),
        _ingest_section(result),
        _search_section(result),
        _overhead_section(records),
        _payload_section(result),
        _plots_section(plots),
    ]
    markdown = "\n\n".join(s for s in sections if s) + "\n"

    report_path = out_dir / "report.md"
    report_path.write_text(markdown)
    return report_path


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m benchmarks.report <result.json> [out_dir]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print("usage: python -m benchmarks.report <result.json> [out_dir]")
        return 0 if args else 2
    result_path = Path(args[0])
    out_dir = Path(args[1]) if len(args) > 1 else None
    report = write_report(result_path, out_dir)
    print(f"wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
