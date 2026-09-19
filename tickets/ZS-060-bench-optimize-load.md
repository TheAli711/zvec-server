---
id: ZS-060
title: optimize-load subcommand: search latency during optimize
spec: SPEC-014
type: feature
priority: P2
status: done
release: v0.2.0
created: 2026-09-16
closed: 2026-09-19
---

# ZS-060: optimize-load subcommand: search latency during optimize

## Summary

Add `python -m benchmarks optimize-load` (SPEC-014 R6–R8) to show whether `optimize`
blocks reads: ingest without optimizing, measure a baseline search window, then keep
searching at the same concurrency while `optimize` runs, and compare QPS, p50, p99,
and max latency. This is the end-to-end check for SPEC-010's shared-lock optimize
(ZS-043).

## Acceptance criteria

- [x] `search_until()` runs closed-loop searches on `concurrency` threads until a
      stop event is set and returns all latencies plus the window length.
- [x] The baseline window ends after `--baseline-seconds` (default `3.0`); the load
      window ends when the background `optimize` returns.
- [x] Each window reports seconds, queries, QPS, p50, p99, and max latency; the
      optimize duration is reported too.
- [x] Results are written as `optimize-load-<scenario>-<tier>-<timestamp>.json` and
      `.md`, and the table is printed.
- [x] Defaults: `--scenario smoke`, `--tier http`, `--concurrency 4`, `--ef` = the
      scenario's first `ef`.
- [x] Unit tests cover `search_until` with a fake runner and `_window`, including an
      empty window.

## Notes

- New `benchmarks/optimize_load.py`, a subparser in `benchmarks/cli.py`, and
  `tests/benchmarks/test_optimize_load.py`.
- Use `inproc` or `http` for the real answer, since they go through the server's
  locking; `engine` is the lock-free control that separates CPU contention from
  blocking.
- Skip the harness's ingest helper, which optimizes; ingest in batches directly so
  the collection is unoptimized when the load window starts.
- Record a before/after comparison against v0.1.2 (exclusive-lock optimize) in the
  README.

## Resolution

Added `benchmarks/optimize_load.py`, the `optimize-load` subparser, unit tests, and a
README section. On the smoke scenario (http tier, c=4) v0.1.2 completed 8 queries
during a 2.1 s optimize with a 2,112 ms max latency; the shared-lock server completed
2,609 in 1.5 s with a 19 ms max. The QPS drop that remains also shows on the `engine`
tier, so it is CPU contention, not blocking.
