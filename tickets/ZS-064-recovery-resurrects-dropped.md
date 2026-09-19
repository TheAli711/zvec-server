---
id: ZS-064
title: Background recovery can resurrect a dropped collection
spec: SPEC-009
type: bug
priority: P1
status: done
release: v0.2.0
created: 2026-09-19
closed: 2026-09-19
---

# ZS-064: Background recovery can resurrect a dropped collection

## Summary

The SPEC-009 recovery task for an unavailable collection can race with `drop()`. If
a retry's open succeeds just as the collection is dropped, the task attaches the new
Zvec handle to the dropped `ManagedCollection`. The entry reads as available again,
and the handle is never closed: the entry is no longer in the registry, so shutdown
skips it, and the Zvec handle and its open files leak for the life of the process.

## Reproduction

1. Start the server while a collection can't be opened (e.g. a rolling restart
   where the previous instance still holds Zvec's lock). It is marked unavailable
   and `start_recovery()` spawns `_recover()` for it.
2. Send `DELETE /collections/{name}` while a retry's `_open_record()` is running in
   the threadpool and about to succeed.
3. `drop()` takes the exclusive lock, sees `available == False` (the handle is not
   attached yet), removes the directory, sets `dropped = True`, drops the registry
   entry, and calls `task.cancel()` from its worker thread. The cancel only lands at
   the task's next `await`, after the open has returned.

Observed: `_recover()` runs `managed.collection = reopened.collection` on the
dropped entry, which then reads as available while its handle leaks. The loop also
checked only `available`, so nothing but the cancel stopped it retrying.
Expected: the late handle is discarded and closed, and the loop stops once dropped.

## Acceptance criteria

- [x] The reopened handle is attached only under the collection's exclusive lock,
      and only if `dropped` is still false.
- [x] If the collection was dropped, the reopened handle is closed (failures
      logged, not raised) and the "Recovered" log line is not emitted.
- [x] `_recover()` exits once `managed.dropped` is set instead of retrying.
- [x] A unit test forces the race deterministically: the open succeeds, `dropped` is
      set, the handle is refused, and `_recover()` returns promptly.
- [x] CHANGELOG `Fixed` entry added.

## Notes

- Module: `manager.py` (`_recover`, new `_adopt` helper); test in
  `tests/unit/test_manager.py`. `drop()` sets `dropped` under `gen_wlock()`, so the
  check-and-assign must happen under the same lock, not before it.

## Resolution

Added `CollectionManager._adopt()`, which installs the reopened handle under the
exclusive lock unless the collection was dropped, and otherwise closes it via
`zcol.close_collection`. `_recover()` now also stops when `dropped` is set. Covered by
`test_recovery_does_not_resurrect_a_dropped_collection`, with a CHANGELOG entry.
