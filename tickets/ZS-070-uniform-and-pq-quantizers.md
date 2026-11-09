---
id: ZS-070
title: Uniform and PQ quantizers
spec: SPEC-015
type: feature
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-070: Uniform and PQ quantizers

## Summary

Accept Zvec 0.8.1's `uniform_uint4` / `uniform_uint7` / `uniform_uint8` (hnsw,
l2) and `pq` (hnsw, ivf; FP32) quantize types, plus the PQ settings `num_chunk`,
`num_bits`, `fast_scan`, `opq_iter`, and `opq_pq_iter`. The server validates every
combination itself, because Zvec's errors for bad PQ values are generic, and some
invalid inputs crash the engine's constructor.

## Acceptance criteria

- [x] `enums.QUANTIZE_TYPES` has the seven tokens, and `parse_quantize_type`
      resolves them case-insensitively.
- [x] Per-index allowed quantize types are enforced: uniform on `hnsw` only, with
      metric `l2`; `pq` on `hnsw`/`ivf` only, with dtype `VECTOR_FP32`. Violations
      return `422` with `details.valid`.
- [x] `num_chunk` must be in 1..dim, `num_bits` must be 4 or 8, and `opq_iter` /
      `opq_pq_iter` must be ≥ 1. `fast_scan` is `ivf` only and needs
      `num_bits: 4`. `opq_*` need `enable_rotate: true`. PQ keys without
      `quantize_type: "pq"` return `422`. Wrong JSON types return `422`.
- [x] `enable_rotate` with a uniform quantizer returns `422`. The engine would
      fail with "Failed to create index".
- [x] Unit tests cover the build matrix and every rejection. Integration tests
      create each new type over HTTP, check the `index_param` echo, and get the
      exact match first after optimize (PQ uses the refiner). A restart keeps the
      params.

## Notes

- Modules: `adapter/enums.py`, `adapter/schema_mapper.py`, and the
  `VectorFieldSpec.params` description.
- With PQ, `enable_rotate` means learned OPQ, not a random rotation.

## Resolution

Added `SCALAR_QUANTIZE_TYPES` / `UNIFORM_QUANTIZE_TYPES` to the enums, a
per-index allowed-type table, and checks for metric (uniform → l2) and dtype
(pq → FP32) in the schema mapper. PQ settings are validated in `_pq_kwargs`,
including the default `num_chunk` (8) against small dimensions, and folded into
the single `QuantizerParam`. Unit tests cover the build and rejection matrix.
Integration tests create every new type over HTTP, check the `index_param`
echo, find the exact match after optimize, and survive a restart.

A review before merge added three fixes. `opq_iter`/`opq_pq_iter` are capped at
100: Zvec takes uint32, so 2**32 was a 500, and huge values would make
optimize run almost forever while holding the maintenance mutex. `fast_scan`
now requires `num_chunk` to divide `dim`, because Zvec's error for that case
is misleading. Rotation is limited to int8/int4/pq (ZS-077).
