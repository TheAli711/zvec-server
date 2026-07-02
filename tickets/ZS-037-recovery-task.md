---
id: ZS-037
title: Background recovery task with exponential backoff
spec: SPEC-009
type: feature
priority: P0
status: todo
release: v0.1.2
created: 2026-07-02
---

# ZS-037: Background recovery task with exponential backoff

## Summary

Add the SPEC-009 retry loop. At startup, the manager starts one `asyncio` task for
each collection that `load_all()` left unavailable. Each task sleeps, then retries
the open off the event loop, and backs off exponentially until the open succeeds.
The collection then starts serving requests without a restart. This ticket fixes the
symptom reported in ZS-036.

## Acceptance criteria

- [ ] `CollectionManager.start_recovery()` spawns one task, named `recover-<name>`,
      for each unavailable collection. `create_app`'s lifespan calls it immediately
      after `load_all()`.
- [ ] Each task sleeps for the current delay and then retries the open through
      `_open_record` inside `run_in_threadpool`. After each failure the delay
      doubles, up to the cap, and the task keeps retrying until the open succeeds.
- [ ] When the open succeeds, the task installs the handle on the existing
      `ManagedCollection`, logs `Recovered previously unavailable collection`, and
      exits. `counts()` and `/readyz` reflect the change immediately.
- [ ] Each collection has at most one task. A finished task removes itself from
      `_recovery_tasks` through a done-callback.
- [ ] `get()` remains a non-blocking O(1) lookup. It raises
      `CollectionUnavailableError` while the collection is recovering.
- [ ] Tests: a directory that reappears is reopened without any request, and an open
      that fails twice is attempted exactly three times before the collection
      becomes available.

## Notes

- Reuse `_open_record` so recovery and startup share the missing-directory check, the
  mmap resolution, and the error logging. The manager stays zvec-free.
- `asyncio.create_task` needs a running loop. Call `start_recovery()` from the async
  lifespan, not from synchronous setup.
- Mutate the existing `ManagedCollection` rather than replacing the registry entry,
  so its RW lock and metadata record carry over unchanged.
- Settings come from ZS-038. Cancellation on drop and shutdown is ZS-039.
