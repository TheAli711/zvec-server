---
id: SPEC-014
title: Quantization and optimize-load benchmarks
status: accepted
created: 2026-09-15
release: v0.2.0
---

# SPEC-014: Quantization and optimize-load benchmarks

## Summary

Extend the benchmark suite (SPEC-007) so the two headline claims of the Zvec 0.7.0
work can be measured instead of asserted: that index quantization (SPEC-011) buys a
smaller, faster index for a little recall, and that `optimize` no longer blocks
reads (SPEC-010). We will add `--quantize` / `--rotate` flags to `run`, a `quant`
subcommand that sweeps every quantization variant on one scenario, and an
`optimize-load` subcommand that measures search latency while `optimize` runs. The
docs' quantization guidance will then be rewritten from the measured numbers.

## Motivation

SPEC-011 exposes `quantize_type` (`fp16` / `int8` / `int4`) and `enable_rotate` on
`hnsw`, `flat`, and `ivf` indexes. The docs being written for it describe the benefit
with nominal ratios (roughly 2×, 4×, 8× smaller than FP32) and say rotation usually
recovers recall. None of that has been measured against this server on Zvec 0.7.0,
and Zvec keeps the full-precision vectors next to the quantized index, so the ratios
cannot be taken at face value. Users will enable quantization on production collections
based on what the docs say; the docs must be backed by data.

SPEC-010 moves `optimize` to a shared lock plus a maintenance mutex so searches keep
running during it (ZS-043). Unit tests prove the locking, but not the user-visible
effect — search latency and throughput while a real optimize runs — nor whether
remaining slowdowns are lock contention or plain CPU competition.

## Goals

- Benchmark any scenario with a quantized index on every tier, with no code edits.
- One command that produces a side-by-side table of all quantization variants:
  recall and Δrecall vs FP32, QPS, latency, on-disk size, optimize time, peak RSS.
- One command that compares search QPS and tail latency with and without a
  concurrent `optimize`, through the server's real locking.
- Replace assumed quantization savings in `docs/API.md` with measured results.

## Non-goals

- Benchmarking `hnsw_rabitq` / `ivf_rabitq`. They only run on Linux x86_64 servers;
  the docs will say they have not been benchmarked yet.
- Gating CI on benchmark numbers or running these benchmarks in CI. The suite stays
  optional (`bench` extra) and lint-only in CI, as SPEC-007 set out.
- Changing server behaviour or defaults. Quantization stays opt-in; this spec only
  measures and documents.
- Recommending a variant per workload or auto-tuning index parameters.
- Measuring write throughput during optimize (writes wait by design).

## Requirements

- **R1.** `python -m benchmarks run` must accept `--quantize {fp16,int8,int4}`
  (default: none, full FP32) and `--rotate` (random rotation before quantizing; only
  meaningful with `--quantize`). They set new `CollectionSpec` fields
  `quantize_type: str | None` and `enable_rotate: bool` on the scenario.
- **R2.** Every tier must build the same quantized index. `inproc` and `http` pass
  `quantize_type` / `enable_rotate` in the vector field's `params` through the
  SPEC-011 API (via `CollectionSpec.index_params()`); `engine` passes
  `zvec.QuantizeType` and `zvec.QuantizerParam(enable_rotate=...)` to the native
  `HnswIndexParam`, `IVFIndexParam`, or `FlatIndexParam`.
- **R3.** A `quant` subcommand must sweep the variants `fp32`, `fp16`, `int8`,
  `int8+rot`, `int4`, `int4+rot` (`--variants` selects a comma-separated subset; an
  unknown label exits with the valid list). Options: `--scenario` (default
  `smoke`), `--tier` (default `engine`), `--hdf5`, `--out`, `--query-threads`,
  `--mmap/--no-mmap`, `--measure-seconds`.
- **R4.** For each variant, `quant` must build a fresh collection in its own
  temporary data dir, ingest and optimize the dataset, record on-disk size (sum of
  files in the data dir), optimize seconds, and peak RSS, run the scenario's full
  search grid (recall@k, QPS, p50/p99), then tear down and delete the data dir.
- **R5.** `quant` must write `quant-<scenario>-<tier>-<timestamp>.json` (rows plus
  captured environment) and a Markdown table beside it, one row per variant × grid
  cell, with Δrecall computed against the `fp32` row for the same
  (concurrency, ef, nprobe) cell, and print the table.
- **R6.** An `optimize-load` subcommand must ingest a scenario **without**
  optimizing, run a baseline window of closed-loop `topk=10` searches for
  `--baseline-seconds` (default `3.0`), then start `optimize` in a background thread
  and keep searching at the same concurrency until it returns. Options:
  `--scenario` (default `smoke`), `--tier` (default `http`), `--concurrency`
  (default `4`), `--ef` (default: the scenario's first `ef`), `--hdf5`, `--out`,
  `--query-threads`, `--mmap/--no-mmap`.
- **R7.** `optimize-load` must report, per window, duration, query count, QPS, p50,
  p99, and max latency, plus the optimize duration, as
  `optimize-load-<scenario>-<tier>-<timestamp>.json` and `.md`, and print the table.
- **R8.** On the `inproc` and `http` tiers, `optimize-load` must go through the
  server's own `CollectionManager` locking, so its result reflects what clients see;
  `engine` has no server locks and serves as the control for the engine's own
  behaviour.
- **R9.** Pure helpers (`CollectionSpec.index_params()`, the variant table and its
  Markdown rendering, the search loop and window summary) must have unit tests under
  `tests/benchmarks/` that skip without the `bench` extra.
- **R10.** `benchmarks/README.md` must document the new flags and both subcommands.
  `docs/API.md` and `CHANGELOG.md` must state the measured quantization trade-offs
  and point users at `python -m benchmarks quant` to measure on their own data.

## Design

### CLI

```bash
uv run python -m benchmarks run --scenario sift1m --quantize int8 --rotate
uv run python -m benchmarks quant --scenario sift1m
uv run python -m benchmarks quant --scenario sift1m --tier http --variants fp32,int8,int4+rot
uv run python -m benchmarks optimize-load --scenario smoke --tier http --concurrency 4
```

### Modules

- `benchmarks/spec.py`: `CollectionSpec.quantize_type` / `enable_rotate`;
  `index_params()` adds `{"quantize_type": ..., "enable_rotate": true}` (rotation
  only when set) to the per-index build params and returns `None` when empty.
- `benchmarks/runners/engine.py`: `_build_index_param` merges the quantization
  kwargs into each native index param.
- `benchmarks/cli.py`: the new `run` flags (applied with `dataclasses.replace` on
  the scenario spec) and two subparsers that lazily import their modules, so a
  broken optional dependency cannot break `run`.
- `benchmarks/quant.py`: `VARIANTS: dict[label, (quantize_type, enable_rotate)]`,
  `_table(rows, recall_k)`, `run_quant(args)`. It reuses `harness.measure_ingest`
  and `harness.measure_search` so numbers are comparable with `run`.
- `benchmarks/optimize_load.py`: `search_until(runner, queries, *, concurrency,
  topk, ef, stop)` — `concurrency` worker threads issuing searches until a
  `threading.Event` is set — plus `_window(latencies, seconds)` and
  `run_optimize_load(args)`. The baseline window stops on a `threading.Timer`; the
  load window stops when the optimize thread returns.

### Reading the results

- Compare RSS across variants on the `http` tier (server process only). The
  `engine` tier's RSS includes the benchmark process and its in-memory dataset,
  which is constant across variants, so only deltas are meaningful there.
- Under a blocking optimize, the load window shows a handful of queries and a max
  latency close to the optimize duration. Under a non-blocking optimize, max latency
  stays near the baseline. A QPS drop that also appears on the `engine` tier is CPU
  contention, not locking.

## Acceptance criteria

- `run --quantize int8 --rotate` creates an `int8`, rotated index on all three tiers;
  `index_params()` returns the quantization keys for `hnsw`, `flat`, and `ivf`.
- `quant --scenario smoke` completes and writes a JSON and Markdown table with one
  row per variant and grid cell, with `+0.000` Δrecall on `fp32`.
- `quant --variants bogus` exits with an error naming the valid variants.
- `optimize-load --scenario smoke --tier http` completes and reports both windows and
  the optimize duration.
- Unit tests cover `index_params()` quantization, `VARIANTS`, the Δrecall table,
  `search_until`, and `_window` (including an empty window).
- The quantization section of `docs/API.md` and `benchmarks/README.md` report the
  measured SIFT1M results rather than nominal compression ratios.

## Risks and open questions

- **Single-machine numbers.** Results come from one developer laptop; absolute QPS
  will differ elsewhere. The docs will state the setup and present the numbers as a
  reason to measure, not as guarantees.
- **Dataset dependence.** SIFT1M is 128-dimensional; quantization may behave
  differently on 768-dim embeddings (the `cohere*` scenarios need a local HDF5).
- **Sweep cost.** Six rebuilds of a 1M-vector collection take a while; `--variants`
  keeps iteration cheap.
- **Tier fidelity.** The `inproc` tier re-implements the server's lock usage around
  adapter calls. If it drifts from the server (as it can when SPEC-010 changes
  locking), `optimize-load` on `inproc` would measure the wrong thing; the `http`
  tier is the reference.

## Tickets

- ZS-058 — --quantize and --rotate benchmark flags
- ZS-059 — quant subcommand to sweep quantization variants
- ZS-060 — optimize-load subcommand: search latency during optimize
- ZS-061 — Report measured quantization trade-offs in the docs
