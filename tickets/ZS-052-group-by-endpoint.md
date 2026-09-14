---
id: ZS-052
title: Group-by search endpoint
spec: SPEC-012
type: feature
priority: P1
status: todo
release: v0.2.0
created: 2026-09-14
---

# ZS-052: Group-by search endpoint

## Summary

Implement `POST /collections/{name}/search/group-by` per SPEC-012: new request and
response models, an adapter function that calls Zvec's `group_by_query`, and a route
that runs it under the collection's shared lock. Include integration tests for the
happy path, filtering, and every `400`/`404` case, plus the API reference entry and
CHANGELOG line.

## Acceptance criteria

- [ ] `GroupSearchRequest`, `GroupOut`, and `GroupSearchResponse` exist in
      `models/search.py` with the SPEC-012 defaults and bounds (`group_count` 10,
      `topk_per_group` 3, both 1–1000).
- [ ] `operations.group_search` rejects an unknown `group_by` with `400` and the
      sorted list of valid scalar fields, even on an empty collection.
- [ ] Malformed filters and index-inappropriate search `params` return `400`; a
      missing collection returns `404`.
- [ ] Group values are strings, groups and hits are best first, and each hit is a
      `DocOut`.
- [ ] Integration tests cover grouping, grouping with a filter, the `400` cases, and
      `404`.
- [ ] `docs/API.md`, the README route table, and `CHANGELOG.md` describe the route.

## Notes

- Modules: `models/search.py`, `adapter/operations.py`, `api/vectors.py`,
  `tests/integration/test_search_api.py`. No manager changes: reuse
  `ManagedCollection.read`.
- Reuse `query_mapper.build_queries` with `vector_index_types(collection)` so the
  SPEC-011 per-index `params` validation applies unchanged.
- Zvec only validates the group field and the filter when there is data to search;
  seed the collection in the `400` tests, and pre-validate `group_by` against
  `collection.schema.fields` in the adapter so empty collections behave the same.
- Only the adapter may import `zvec`.
