---
id: ZS-071
title: Refiner search params for hnsw, hnsw_rabitq, and ivf
spec: SPEC-015
type: feature
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-071: Refiner search params for hnsw, hnsw_rabitq, and ivf

## Summary

Zvec 0.8.1 adds `scale_factor` to `HnswQueryParam`/`HnswRabitqQueryParam`, and
both `is_using_refiner` and `scale_factor` to `IVFQueryParam`. The refiner
re-scores a larger candidate set against the full-precision vectors. That is what
makes PQ and the uniform quantizers usable: in a synthetic check, PQ's recall@10
went from 0.66 to 1.00.

## Acceptance criteria

- [x] `hnsw` and `hnsw_rabitq` accept `scale_factor`. `ivf` accepts
      `is_using_refiner` and `scale_factor`. Types are checked the same way as
      other search params (bool vs. number).
- [x] `scale_factor < 0` returns `400`.
- [x] Integration tests: an `ivf` + `pq` search with the refiner returns the
      exact match first. `scale_factor` on `flat` and on `ivf_rabitq`-only keys
      keep their current behavior.
- [x] The `QuerySpec.params` description and the docs/API.md table list the new
      keys, along with the differing defaults (HNSW 0 means max(topk, ef); IVF
      defaults to 10).

## Resolution

Added `scale_factor` to the hnsw / hnsw_rabitq param set, and `is_using_refiner`
+ `scale_factor` to ivf. `scale_factor < 0` returns 400. Integration tests run
ivf + pq and ivf + pq + FastScan with the refiner, and cover refiner params on
plain ivf and int8 hnsw, plus the new 400 cases.

A review before merge capped `scale_factor` at 1000. Above roughly
`scale_factor × topk ≥ 2**31`, the engine fails inside Gandiva and the server
returned 500, and this applies to `ivf_rabitq` too. Non-finite floats (`NaN`,
`Infinity`, which the JSON parser accepts) are now rejected for every float
param. The PQ refiner test now checks for an exact 0 distance, because
without the refiner the exact match often still ranks first.
