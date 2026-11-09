---
id: ZS-069
title: Reject enable_rotate on hnsw scalar quantization (Zvec 0.8 regression)
spec: SPEC-015
type: bug
priority: P0
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-069: Reject enable_rotate on hnsw scalar quantization (Zvec 0.8 regression)

## Summary

On Zvec 0.8.0 and 0.8.1, a **newly created** HNSW index with `int8`/`int4`
quantization and `enable_rotate: true` returns near-random results after
`optimize`. Flat and IVF with rotation are fine, and so are HNSW collections
built with 0.7.0. Reject the combination at create time with a `422` that
explains why, instead of building a collection that silently returns wrong
answers.

## Reproduction

64-d Gaussian vectors, 500 docs, cosine, `HnswIndexParam(quantize_type=INT8,
quantizer_param=QuantizerParam(enable_rotate=True))`, insert, optimize, then
query each doc with its own vector at `topk=1`:

| zvec   | self-recall@1, rotate off | self-recall@1, rotate on |
| ------ | ------------------------- | ------------------------ |
| 0.7.0  | 100/100                   | 100/100                  |
| 0.8.0  | 100/100                   | 0/100                    |
| 0.8.1  | 100/100                   | 1–2/100                  |

`tests/integration/test_search_api.py::test_quantized_collection_roundtrip`
(4-d, `int8` + rotation, hnsw) catches it: the exact match no longer ranks
first.

## Acceptance criteria

- [x] `hnsw` + `enable_rotate: true` + `fp16`/`int8`/`int4` returns
      `422 schema_validation_error`, naming the quantize type and the upstream
      cause.
- [x] `hnsw` + `pq` + `enable_rotate` (OPQ) is still accepted. Its recall matches
      PQ without OPQ.
- [x] `flat` and `ivf` with rotation keep working. The int8 + rotation round-trip
      test runs on `flat`/`ivf`, and a new test covers the `hnsw` rejection.
- [x] CHANGELOG notes the breaking change and that existing collections are
      unaffected.

## Notes

- The check sits in `schema_mapper._quantize_kwargs`, keyed on the index type, so
  ZS-076 can lift it by deleting one branch.
- `enable_rotate: false` stays accepted. It is a no-op.

## Resolution

Reported upstream as https://github.com/alibaba/zvec/issues/886.
Added `schema_mapper._check_rotation`, which rejects hnsw + `fp16`/`int8`/`int4`
+ `enable_rotate: true` with a 422 naming the upstream cause. `enable_rotate:
false` and pq + OPQ on hnsw stay accepted. The int8 + rotation round trip now
runs on flat and ivf, and new unit and integration tests cover the rejection.
The engine-level reproduction is kept here so the bug can be reported upstream
and the guard lifted later (ZS-076).
