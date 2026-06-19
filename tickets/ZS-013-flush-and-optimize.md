---
id: ZS-013
title: Flush and optimize endpoints
spec: SPEC-002
type: feature
priority: P1
status: in-progress
release: v0.1.0
created: 2026-06-15
---

# ZS-013: Flush and optimize endpoints

## Summary

Add `POST /collections/{name}/flush` (persist buffered writes) and
`POST /collections/{name}/optimize` (segment merge and index build), and flush all
open collections at shutdown so a clean stop does not lose buffered writes.

## Acceptance criteria

- [ ] Both endpoints resolve the collection via `manager.get` (404 unknown, 503
      unavailable) and run the adapter call under the exclusive write lock.
- [ ] Flush returns `{"message": "Collection '<name>' flushed."}`; optimize returns
      `{"message": "Collection '<name>' optimized."}`.
- [ ] Engine failures surface as `500 zvec_operation_error`.
- [ ] `CollectionManager.close()` flushes every open collection under its write
      lock, logging and continuing past individual failures, then clears the
      registry.
- [ ] An integration test calls flush and optimize on a fresh collection.

## Notes

- Optimize is synchronous: the request returns when the engine finishes, and the
  write lock blocks reads and writes on that collection meanwhile. Fine for
  v0.1.0 data sizes; a background job API is out of scope.
- Optimize uses the engine's default `OptimizeOption()`; no tuning knobs are
  exposed yet.
- The routes call `adapter.collections` directly through `managed.write`, which
  the api → adapter import direction allows.
