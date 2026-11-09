---
id: ZS-072
title: Refiner on an unquantized hnsw field returns 500
spec: SPEC-011
type: bug
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-072: Refiner on an unquantized hnsw field returns 500

## Summary

`is_using_refiner: true` is accepted on any `hnsw` field (SPEC-011). On an fp32
HNSW index, Zvec 0.7.0 and 0.8.1 fail once the collection has been optimized,
and the server returns `500 zvec_operation_error`. There is nothing to refine
without quantization, so reject it as a bad request.

## Reproduction

Create an `hnsw` collection with no `quantize_type`, insert, optimize, then search
with `"params": {"is_using_refiner": true}`. Actual: `500`, "Read next record batch
failed (fill_result): ExecutionError in Gandiva". Before optimize the same request
succeeds. The same holds with `scale_factor < 0` on any refining field.

## Acceptance criteria

- [x] `is_using_refiner: true` on an `hnsw` field whose `quantize_type` is
      `UNDEFINED` returns `400 invalid_argument`. `false` stays accepted.
- [x] The rule reads the quantize type from the open collection's schema, not from
      the request.
- [x] Quantized `hnsw` and `ivf`, with or without quantization, still accept the
      refiner.
- [x] Regression tests cover the 400 and the allowed cases.

## Resolution

`vector_index_types()` became `vector_index_info()`, which returns `(index_type,
quantize_type)` from the open collection's schema. The query mapper now
rejects `is_using_refiner: true` on `HNSW` + `UNDEFINED` with a 400. A
regression test reproduces the post-optimize 500 path. Both 0.7.0 and 0.8.1
failed this way, so it was a SPEC-011 bug, not a 0.8 regression.
