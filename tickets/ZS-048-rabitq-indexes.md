---
id: ZS-048
title: hnsw_rabitq and ivf_rabitq index types
spec: SPEC-011
type: feature
priority: P1
status: done
release: v0.2.0
created: 2026-09-11
closed: 2026-09-19
---

# ZS-048: hnsw_rabitq and ivf_rabitq index types

## Summary

Add Zvec 0.7.0's RaBitQ index families as two new `vectors[].index` values:
`hnsw_rabitq` and `ivf_rabitq`. The engine supports them only on Linux x86_64. On
any other platform, create must fail with a clear `422` and leave nothing
registered, rather than a `500`.

## Acceptance criteria

- [x] `enums.INDEX_TYPES` includes `hnsw_rabitq` and `ivf_rabitq`.
- [x] `hnsw_rabitq` accepts `m`, `ef_construction`, `total_bits`, `num_clusters`,
      and `sample_count`. `ivf_rabitq` accepts `n_list`, `total_bits`, and
      `sample_count`. All must be integers. Other keys return 422 (ZS-047).
- [x] `ivf_rabitq`'s `n_list` maps to Zvec's `nlist` kwarg, so the API name stays
      the same across IVF kinds. The echoed `index_param` shows `nlist`.
- [x] The engine's "not supported on this platform" `RuntimeError` becomes
      `SchemaValidationError` (422). No collection is registered, and
      `GET /collections/{name}` returns 404.
- [x] On Linux x86_64, both types create, optimize, and return `topk` hits from
      search by id.

## Notes

- Modules: `adapter/enums.py`, `adapter/schema_mapper.py` (build
  `HnswRabitqIndexParam`/`IvfRabitqIndexParam`; RaBitQ quantizes by construction,
  so `quantize_type`/`enable_rotate` are not accepted), and
  `adapter/collections.py` (map the platform error in `create_collection`).
- Platform support is detected by matching the engine's error message. Make the
  integration test assert that message, so an upstream rewording fails CI instead
  of silently turning into a 500.
- Developers on macOS only exercise the 422 path. The Docker image and the Linux
  CI runners exercise the success path.
- Query params for RaBitQ fields come with ZS-049.

## Resolution

Added both index types to the enum set, their allow-lists and builders to the
schema mapper (with the `n_list` → `nlist` rename), and the platform-error mapping
to `create_collection`. A platform-aware integration test checks both outcomes, and
the API docs and CHANGELOG note the Linux x86_64 restriction.
