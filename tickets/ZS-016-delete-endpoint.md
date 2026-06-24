---
id: ZS-016
title: Delete documents by ids or by filter
spec: SPEC-003
type: feature
priority: P0
status: done
release: v0.1.0
created: 2026-06-16
closed: 2026-06-24
---

# ZS-016: Delete documents by ids or by filter

## Summary

Add `POST /collections/{name}/docs/delete` taking exactly one of `ids` or a
SQL-like `filter`. Id deletes report per-id status; filter deletes pass the filter
to Zvec verbatim and echo it back, since the engine returns no per-document status.

## Acceptance criteria

- [x] `DeleteRequest` has optional `ids` and `filter` with a model validator
      rejecting neither/both → `422 validation_error`.
- [x] Id deletes call `collection.delete(ids)` and return `results` per id and
      `ok` = every item ok.
- [x] Filter deletes call `collection.delete_by_filter(filter)` and return
      `{"ok": true, "filter": <filter>, "message": "Deleted by filter."}`.
- [x] A malformed filter → `400 invalid_argument` with `details.filter`; other
      engine failures → `500 zvec_operation_error`.
- [x] The route runs under the exclusive write lock; tests cover id delete (then
      fetch shows only the survivor), filter delete, and the 422 cases.

## Notes

- Filters use Zvec syntax: single `=`, single-quoted strings, `AND`/`OR`/`NOT`,
  `IN`, `BETWEEN`, `LIKE`. Do not translate `==` or rewrite anything; document the
  syntax instead.
- `DeleteResponse` fields not used by a mode stay `null` so the shape is stable
  for clients.
- There is no count of deleted documents for filter deletes; callers that need one
  must query before or after.

## Resolution

Added `DeleteRequest`/`DeleteResponse`, `operations.delete`, and the route in
`api/vectors.py`, with model and integration tests. The filter-delete integration
test flushes the collection before issuing the delete.
