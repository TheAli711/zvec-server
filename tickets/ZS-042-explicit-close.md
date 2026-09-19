---
id: ZS-042
title: Close collection handles explicitly on shutdown
spec: SPEC-010
type: feature
priority: P1
status: done
release: v0.2.0
created: 2026-09-09
closed: 2026-09-19
---

# ZS-042: Close collection handles explicitly on shutdown

## Summary

`CollectionManager.close()` flushes and clears the registry, but it never closes the
Zvec handles. Their file handles and on-disk lock stay held until garbage collection
or process exit. A replacement instance in a rolling restart then finds the
collections locked, marks them unavailable, and waits for recovery backoff
(SPEC-009, ZS-036). Use Zvec 0.7.0's `Collection.close()` to release each handle
deliberately during shutdown.

## Acceptance criteria

- [x] `adapter/collections.py` exposes `close_collection(collection)`, which wraps
      `collection.close()` and maps engine failures to `ZvecOperationError`.
- [x] `manager.close()` closes every open handle under that collection's exclusive
      lock, after flushing and after cancelling recovery tasks.
- [x] Each entry's handle is set to `None` before it is closed. A lingering
      reference reports `available == False`, and `read()`/`write()` on it raise
      `CollectionUnavailableError` (503).
- [x] A second manager on the same data directory can `load_all()` right after
      the first one closes, with every collection available.
- [x] A close failure on one collection is logged and does not stop shutdown.

## Notes

- Modules: `adapter/collections.py` (new helper, the only place that calls
  `close()`), `manager.py` (`close()`).
- Take the exclusive lock so in-flight searches and writes finish before the handle
  goes away. A closed handle is unusable, so nothing may reach the engine through it
  afterwards.
- Unavailable entries (`collection is None`) are skipped. There is nothing to close.
- Unit test: create, keep a reference, close, assert the reference is unavailable,
  then reopen the same directory from a fresh manager and store.

## Resolution

Added `close_collection` to the adapter and extended `CollectionManager.close()`. It
snapshots and clears the registry, then, under each entry's exclusive lock, detaches
the handle and closes it, logging any failure. A unit test covers the stale
reference (503) and an immediate reopen by a second manager.
