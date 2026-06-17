---
id: ZS-019
title: Search endpoint with multi-query and output control
spec: SPEC-004
type: feature
priority: P0
status: todo
release: v0.1.0
created: 2026-06-17
---

# ZS-019: Search endpoint with multi-query and output control

## Summary

Expose `POST /collections/{name}/search` on the documents router. It accepts one or
more queries, returns a flat `SearchResponse` of `DocOut` hits with `score` set, and
lets callers choose whether vectors come back (`include_vector`) and which scalar fields
are returned (`output_fields`). The search runs under the collection's shared read lock
in a worker thread, like fetch.

## Acceptance criteria

- [ ] `POST /collections/{name}/search` returns 200 with `{"results": [...]}`, each hit a
      `DocOut` with `id`, `score`, `vectors` (only when `include_vector` is true), and
      `fields`.
- [ ] `output_fields` restricts the scalar fields in each hit; `null` returns all.
- [ ] Several queries in one request run through a single engine call; search by `id`
      returns the referenced document among the hits.
- [ ] The handler resolves the collection with `manager.get` (404 missing, 503
      unavailable) and runs via `managed.read`, never blocking the event loop.
- [ ] A filter using `==` returns 400 `invalid_argument`; a query with neither `vector`
      nor `id` returns 422.
- [ ] An integration test restarts the app on the same data directory and gets the same
      hit back.

## Notes

- Modules: `api/vectors.py` (route), `models/search.py` (`include_vector`,
  `output_fields`, `SearchResponse`). Depends on ZS-018 for the adapter call and on
  ZS-011 for `ManagedCollection.read`.
- Hits use the same `DocOut` as fetch (ZS-017), so the output shape stays identical
  across read endpoints.
- Tests belong in `tests/integration/test_search_api.py`, seeding with insert + flush
  against a real engine in `tmp_path`.
- Open question carried from SPEC-004: multi-query merge order is the engine's; do not
  promise more than "best first" for a single query in the docs.
