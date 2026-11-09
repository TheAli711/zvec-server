---
id: ZS-074
title: Benchmark the new quantizers and the refiner
spec: SPEC-015
type: chore
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-074: Benchmark the new quantizers and the refiner

## Summary

Extend the `quant` sweep (SPEC-014) with the uniform and PQ variants and a
refiner dimension, so the docs can report measured trade-offs rather than
assumed ones (the ZS-061 approach).

## Acceptance criteria

- [x] `python -m benchmarks quant` accepts the uniform, PQ, and PQ + OPQ variants,
      plus a refiner option, on the engine and http tiers. The http tier sends the
      SPEC-015 param names.
- [x] The refiner is never applied to fp32 hnsw (ZS-072).
- [x] Bench tests pass and `benchmarks/README.md` documents the flags.
- [x] A SIFT1M run's results are saved under `benchmarks/results/`.

## Resolution

Added uniform, PQ, PQ + OPQ, and IVF PQ4 + FastScan variants to the quant
sweep, with a `--refine` scale-factor axis (never applied to fp32 hnsw) and
`--index` / `--ef` / `--nprobe` / `--concurrency` / `--pq-chunks` flags.
`skip_reason()` and per-variant error capture let a sweep continue past
combinations a tier rejects, for example the server's 422 for hnsw + int8 +
rotation. The http optimize request timeout went from 120 s to 1800 s, since PQ
training on 1M vectors exceeded it. The SIFT1M engine and http runs are under
`benchmarks/results/zvec081/` (git-ignored). On 1M vectors they confirm
recall@10 = 0.000 for hnsw + int8/int4 + rotation.
