---
id: ZS-080
title: Shutdown lets a queued optimize run between flush and close
spec: SPEC-010
type: bug
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-080: Shutdown lets a queued optimize run between flush and close

## Summary

`CollectionManager.close()` first ran `flush_all()`, which took and released
each collection's exclusive lock, and then took the exclusive lock **again**
to close the handle. An optimize queued behind the shutdown could take the
shared lock in that gap and run a full optimize against a collection that was
being shut down. That delays shutdown, and the queued request succeeds when it
should fail with `CollectionUnavailableError`.

## Reproduction

`tests/unit/test_manager.py::test_drop_or_close_waits_for_a_running_optimize[close]`
failed on CI (Linux, Python 3.12, Zvec 0.8.1) with "DID NOT RAISE
CollectionUnavailableError". It passes locally, so it's a timing race; Zvec
0.8.1's timing made the window easier to hit.

## Acceptance criteria

- [x] Each collection is flushed and closed under one exclusive-lock hold, with
      nothing able to run in between.
- [x] The existing drop/close-during-optimize test passes on CI for 3.12 and 3.13.

## Resolution

`close()` now flushes and closes each handle inside the same `gen_wlock()`
block, after releasing its cursors. The handle is detached first, so anything
queued sees the collection as unavailable. The unused `flush_all()` was
removed. `drop()` already did its work under a single exclusive hold.
