---
id: ZS-043
title: Serve reads while optimize runs
spec: SPEC-010
type: feature
priority: P1
status: done
release: v0.2.0
created: 2026-09-09
closed: 2026-09-19
---

# ZS-043: Serve reads while optimize runs

## Summary

`POST /collections/{name}/optimize` currently runs under the collection's exclusive
write lock. Every search and fetch on that collection waits for the whole merge or
index build. Zvec 0.7.0 serves reads during optimize, so optimize should take only
the shared lock. A per-collection mutex will keep two optimizes from overlapping.

## Acceptance criteria

- [x] `ManagedCollection.maintain(fn)` runs `fn` in a worker thread while holding a
      per-collection `maintenance_lock` and then the shared read lock, in that
      order.
- [x] The optimize route calls `managed.maintain(optimize_collection)` instead of
      `managed.write(...)`. The response stays
      `200 {"message": "Collection '<name>' optimized."}`.
- [x] A read on the collection completes while a maintenance call is running. A
      write stays pending until it finishes.
- [x] Concurrent optimize calls on one collection are serialized.
- [x] Shutdown still waits for a running optimize, because it takes the exclusive
      lock.

## Notes

- Modules: `manager.py` (`ManagedCollection`), `api/collections.py` (optimize
  route and docstring).
- Take the mutex before the shared lock. A queued second optimize then waits on the
  mutex and does not hold a reader slot.
- Flush stays on `write()`. Only optimize moves to `maintain()`.
- Test with a fake maintenance function that blocks on a `threading.Event`, so
  results do not depend on how long a real optimize takes.
- Risk: under `RWLockFair`, a writer queued behind optimize can hold back later
  readers. Accept this for now and note it in SPEC-010.

## Resolution

Added `maintenance_lock` and `maintain()` to `ManagedCollection`. The optimize
endpoint now uses them, and a unit test shows reads proceed while writes wait. A
later test confirmed that `drop()` and `close()` both wait for a running optimize,
not failing or deadlocking. An optimize queued behind them then fails cleanly with
`CollectionUnavailableError`.
