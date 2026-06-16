---
id: ZS-015
title: Insert, upsert, and update endpoints
spec: SPEC-003
type: feature
priority: P0
status: todo
release: v0.1.0
created: 2026-06-16
---

# ZS-015: Insert, upsert, and update endpoints

## Summary

Add `POST /collections/{name}/docs/insert`, `/docs/upsert`, and `/docs/update`,
sharing a `WriteRequest` body (`docs`, min 1) and the `WriteResponse` shape from
ZS-014. Writes run under the collection's exclusive lock in the threadpool.

## Acceptance criteria

- [ ] `operations.insert(collection, docs, mode)` converts docs, dispatches to
      `collection.insert`, `upsert`, or `update` by `mode`, and builds the
      per-document response.
- [ ] Engine `ValueError` → `400 invalid_argument`; any other engine exception →
      `500 zvec_operation_error`; our own errors propagate unchanged.
- [ ] The three routes call `managed.write(...)`; unknown collection → `404`,
      unavailable → `503`, empty `docs` → `422 validation_error`.
- [ ] Per-document failures return `200` with `ok: false` entries and a non-zero
      `error_count`.
- [ ] Integration tests cover insert with ids, generated ids, missing collection,
      upsert of a new id, and a partial update of one field read back via GET.

## Notes

- Update may omit `vectors` and send only the fields being changed; the engine
  applies it to the existing document.
- No server-side dimension or type checks: Zvec rejects mismatches, and the
  mapping above turns them into `400` or per-document statuses.
- One exclusive lock per batch means large batches delay reads on that collection;
  note this in the docs rather than chunking server-side.
- Routes live in `api/vectors.py` under the `documents` tag.
