---
id: ZS-077
title: fp16 + enable_rotate creates a collection that rejects every insert
spec: SPEC-011
type: bug
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-077: fp16 + enable_rotate creates a collection that rejects every insert

## Summary

SPEC-011 accepted `enable_rotate` with every scalar quantizer. Zvec only rotates
`int8`/`int4` and logs "enable_rotate is only supported for INT8/INT4 quantizer".
With `fp16`, the create succeeds, but every insert returns `ok: false` with
`INTERNAL_ERROR "Create vector column indexer failed"`, so the collection can
never hold data. This affects Zvec 0.7.0 and 0.8.1, on every index type.

## Reproduction

`POST /collections` with `{"index": "flat", "params": {"quantize_type": "fp16",
"enable_rotate": true}}` returns `201`. Then `POST /docs/insert` returns `200`
with every result `ok: false`, and `doc_count` stays 0.

## Acceptance criteria

- [x] `enable_rotate: true` is accepted only with `int8`, `int4`, or `pq`, on
      every index. Other types return `422` with `details.valid`.
- [x] Unit tests cover fp16 + rotation on hnsw, flat, and ivf.
- [x] The docs and CHANGELOG say rotation applies to int8/int4 (and OPQ for pq).

## Resolution

Found in review of the SPEC-015 changes. `_check_rotation` now allow-lists
`int8`/`int4`/`pq` before the hnsw regression guard (ZS-069). The guard now
applies only to int8/int4, so fp16 gets the accurate "not supported" message
instead of the regression one. Existing fp16 + rotation collections stay
loadable, but they could never have held documents.
