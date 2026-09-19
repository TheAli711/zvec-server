---
id: ZS-059
title: quant subcommand to sweep quantization variants
spec: SPEC-014
type: feature
priority: P2
status: done
release: v0.2.0
created: 2026-09-16
closed: 2026-09-19
---

# ZS-059: quant subcommand to sweep quantization variants

## Summary

Add `python -m benchmarks quant` (SPEC-014 R3–R5): rebuild one scenario once per
quantization variant (`fp32`, `fp16`, `int8`, `int8+rot`, `int4`, `int4+rot`) and
emit a single side-by-side table of recall, Δrecall vs FP32, QPS, latency, on-disk
size, optimize time, and peak RSS. This produces the numbers ZS-061 will put in the
docs.

## Acceptance criteria

- [x] `VARIANTS` maps each label to `(quantize_type, enable_rotate)`, with `fp32`
      as `(None, False)`.
- [x] `--variants` selects a subset; an unknown label exits with the valid list.
- [x] Each variant uses a fresh temporary data dir that is removed afterwards, and
      records disk MB, optimize seconds, and peak RSS from ingest.
- [x] The full scenario grid is measured per variant with the existing harness, and
      Δrecall is computed against the `fp32` row for the same grid cell.
- [x] Results are written as `quant-<scenario>-<tier>-<timestamp>.json` plus a
      Markdown table, and the table is printed.
- [x] Unit tests cover `VARIANTS` and the Δrecall column of `_table()`.

## Notes

- New `benchmarks/quant.py`; register the subparser in `benchmarks/cli.py` with a
  lazy import, as `run` does for tiers. Tests in `tests/benchmarks/test_quant.py`
  (skip without numpy).
- Build on ZS-058: each variant is `dataclasses.replace(scenario.spec,
  quantize_type=..., enable_rotate=...)`.
- Default to the `engine` tier; RSS there includes the benchmark process and its
  dataset, so document using `--tier http` when server RSS is the question.
- Measure disk after ingest + optimize, before teardown.

## Resolution

Added `benchmarks/quant.py` (`VARIANTS`, `_table`, `run_quant`), the `quant`
subparser with `--scenario`, `--tier`, `--variants`, `--hdf5`, `--out`,
`--query-threads`, `--mmap`, and `--measure-seconds`, unit tests, and a README
section with example invocations.
