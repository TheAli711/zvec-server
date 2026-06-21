---
id: ZS-016
title: Delete documents by ids or by filter
spec: SPEC-003
type: feature
priority: P0
status: in-progress
release: v0.1.0
created: 2026-06-16
---

# ZS-016: Delete documents by ids or by filter

## Summary

Add `POST /collections/{name}/docs/delete` taking exactly one of `ids` or a
SQL-like `filter`. Id deletes report per-id status; filter deletes pass the filter
to Zvec verbatim and echo it back, since the engine returns no per-document status.

## Acceptance criteria

- [ ] `DeleteRequest` has optional `ids` and `filter` with a model validator
      rejecting neither/both → `422 validation_error`.
- [ ] Id deletes call `collection.delete(ids)` and return `results` per id and
      `ok` = every item ok.
- [ ] Filter deletes call `collection.delete_by_filter(filter)` and return
      `{"ok": true, "filter": <filter>, "message": "Deleted by filter."}`.
- [ ] A malformed filter → `400 invalid_argument` with `details.filter`; other
      engine failures → `500 zvec_operation_error`.
- [ ] The route runs under the exclusive write lock; tests cover id delete (then
      fetch shows only the survivor), filter delete, and the 422 cases.

## Notes

- Filters use Zvec syntax: single `=`, single-quoted strings, `AND`/`OR`/`NOT`,
  `IN`, `BETWEEN`, `LIKE`. Do not translate `==` or rewrite anything; document the
  syntax instead.
- `DeleteResponse` fields not used by a mode stay `null` so the shape is stable
  for clients.
- There is no count of deleted documents for filter deletes; callers that need one
  must query before or after.
