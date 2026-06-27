---
id: ZS-029
title: Benchmark CLI, scenarios, and reports
spec: SPEC-007
type: feature
priority: P1
status: in-progress
release: v0.1.1
created: 2026-06-25
---

# ZS-029: Benchmark CLI, scenarios, and reports

## Summary

Make the suite usable end to end. This ticket adds named scenarios, a
`python -m benchmarks` CLI that runs the selected tiers and prints the overhead
decomposition, a report generator that turns a result JSON into markdown plus plots,
and user docs. Together these connect ZS-026 through ZS-028 into the SPEC-007
workflow.

## Acceptance criteria

- [ ] `python -m benchmarks list` prints `smoke`, `sift1m`, `cohere1m`, and
      `cohere10m`. `run` accepts `--scenario`, `--tiers`, `--hdf5`,
      `--measure-seconds`, `--query-threads`, `--mmap/--no-mmap`, and `--out`.
- [ ] `scenarios.py` defines `SearchGrid`, a cartesian product over topk, ef, nprobe,
      concurrency, filters, and include_vector. It also defines the four scenarios
      with the SPEC-007 parameters. A Cohere scenario without `--hdf5`, or an
      unknown scenario name, raises `ValueError`.
- [ ] Each run gives every tier a fresh temp root and writes
      `<scenario>-<timestamp>.json`. It then prints per-tier summaries and the
      engine → inproc → http p50 table.
- [ ] `report.py` writes `report.md` with environment, ingest, per-tier search,
      overhead decomposition, payload, and plots sections, plus four PNGs under
      `plots/`. It can also run standalone as
      `python -m benchmarks.report <result.json> [out_dir]`.
- [ ] `benchmarks/README.md` documents the tiers, flags, scenarios, how to read the
      results, and the caveats. The root README links to it, and CHANGELOG has an
      Added entry.
- [ ] The unit tests for scenarios and the grid pass.

## Notes

- Load datasets lazily so that `list` returns instantly.
- The report reads the JSON as dicts, so partial runs with `None` fields still render.
  matplotlib runs with the `Agg` backend, which needs no display.
- Write the JSON first. A report failure must never lose the measurements.
- Match cells across tiers on (topk, ef, nprobe, concurrency, filter).
  `include_vector` is not stored on results.
