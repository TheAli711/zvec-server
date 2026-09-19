---
id: ZS-047
title: Reject unknown vector index params instead of ignoring them
spec: SPEC-011
type: bug
priority: P1
status: done
release: v0.2.0
created: 2026-09-11
closed: 2026-09-19
---

# ZS-047: Reject unknown vector index params instead of ignoring them

## Summary

The schema mapper reads only the `vectors[].params` keys it knows for the index type
and silently drops the rest. A typo, or a key meant for another index type, creates
a collection with a different index than the client asked for, and the response is
still `201`. With quantization coming (ZS-045), `quantize` instead of
`quantize_type` would quietly build a full-precision index.

## Reproduction

`POST /collections` with an `hnsw` field whose params contain a typo and an IVF key:

```json
{ "name": "articles", "vectors": [{ "name": "embedding", "dim": 4, "index": "hnsw",
    "params": { "ef_constrution": 200, "n_list": 8 } }] }
```

Observed: `201 Created`. `index_param` shows Zvec's default `ef_construction`, and
neither key is mentioned anywhere. Expected: `422 schema_validation_error` naming
`ef_constrution` and `n_list` and listing the keys `hnsw` accepts.

## Acceptance criteria

- [x] Each index type has an allow-list of `params` keys, checked before any index
      param object is built.
- [x] Unknown keys raise `SchemaValidationError` (422) with message
      `Unknown parameter(s) for '<index>' index: ...` and details
      `{"unknown": [...], "valid": [...]}`, both sorted.
- [x] Cross-index keys are rejected: `n_list` on `hnsw`, `m` on `flat`,
      `ef_construction` on `ivf`, and the `quantize` typo.
- [x] Valid params for every index type still build unchanged.
- [x] The CHANGELOG records the behaviour change.

## Notes

- Module: `adapter/schema_mapper.py` (`_INDEX_PARAMS`, `_check_param_keys`). The
  allow-lists must include `quantize_type`/`enable_rotate` (ZS-045) and
  `use_soar` (ZS-046). RaBitQ (ZS-048) adds its own entries.
- Breaking for clients that send stray keys today. SPEC-011 puts it in a minor
  release with a CHANGELOG callout.
- Search `params` have the same silent-ignore problem. That fix is part of ZS-049,
  which returns 400 instead because it is a request argument, not a schema.

## Resolution

Added per-index allow-lists and a key check at the top of
`_build_vector_index_param`, so unknown keys now return 422 with the unknown and
valid keys in the details. Parametrized unit tests cover typos and cross-index keys.
The change is listed under *Changed* in the CHANGELOG.
