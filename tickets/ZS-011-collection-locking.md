---
id: ZS-011
title: Per-collection reader/writer lock and threadpool offload
spec: SPEC-002
type: feature
priority: P0
status: done
release: v0.1.0
created: 2026-06-15
closed: 2026-06-24
---

# ZS-011: Per-collection reader/writer lock and threadpool offload

## Summary

Give each `ManagedCollection` a fair reader/writer lock and two helpers,
`read(fn)` and `write(fn)`, that run a blocking engine call in Starlette's
threadpool under the right lock. Reads on one collection must proceed in parallel,
writes must be exclusive, and the asyncio event loop must never wait on a lock.

## Acceptance criteria

- [x] Each `ManagedCollection` owns a `readerwriterlock.rwlock.RWLockFair`.
- [x] `await managed.read(fn)` runs `fn(handle)` via `run_in_threadpool` inside
      `gen_rlock()`; `await managed.write(fn)` does the same inside `gen_wlock()`.
- [x] The lock is acquired inside the worker thread, not on the event loop.
- [x] Both helpers raise `CollectionUnavailableError` (503) when the handle is
      `None`.
- [x] Collection-level endpoints that call manager methods directly (create, list,
      info, drop) are also dispatched with `run_in_threadpool`.

## Notes

- Fair locking prevents a stream of readers from starving writers (and vice
  versa).
- Lock scope is one collection; operations on different collections never contend.
- Read-lock users: fetch, search, stats. Write-lock users: insert, upsert, update,
  delete, flush, optimize, and the shutdown flush.
- Adds the `readerwriterlock` runtime dependency (typed as missing-imports in mypy).
- The default threadpool size bounds concurrent engine calls; revisit if it
  becomes a bottleneck with a single worker.

## Resolution

Implemented `ManagedCollection.read`/`write` in `manager.py` with the lock taken
inside the threadpool worker. Stats reads in `list()`/`info()` also use the shared
lock.
