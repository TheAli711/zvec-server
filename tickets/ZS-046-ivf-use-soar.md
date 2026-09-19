---
id: ZS-046
title: use_soar for ivf indexes
spec: SPEC-011
type: feature
priority: P2
status: done
release: v0.2.0
created: 2026-09-11
closed: 2026-09-19
---

# ZS-046: use_soar for ivf indexes

## Summary

Zvec 0.7.0's IVF index can use SOAR spilling: a vector is also assigned to a
secondary cluster, which improves recall at a given `nprobe`. Expose it as a boolean
`vectors[].params.use_soar` on `ivf` fields, next to `n_list` and `n_iters`.

## Acceptance criteria

- [x] `ivf` accepts `params.use_soar` (JSON boolean) and passes it to
      `zvec.IVFIndexParam(use_soar=...)`.
- [x] A non-boolean value returns 422 `schema_validation_error`.
- [x] The built schema echoes `use_soar` in `index_param`, alongside `n_list` and
      `n_iters`.
- [x] The `docs/API.md` params table, the `VectorFieldSpec.params` description, and
      the CHANGELOG list `use_soar` for `ivf`.

## Notes

- Modules: `adapter/schema_mapper.py`. Reuse the `_bool_param()` validator from
  ZS-045.
- `ivf` only. `use_soar` on another index type must be rejected once ZS-047 lands.
- SOAR spills vectors, so the index grows. Leave it off by default (Zvec's default)
  and don't recommend it without measurements.
- Restart persistence is covered by ZS-050.

## Resolution

The `ivf` builder now reads `use_soar` via `_bool_param()` and passes it to
`IVFIndexParam`. The existing IVF schema-mapper test was extended to assert the
echoed value. The API params table, model description, and CHANGELOG were updated.
