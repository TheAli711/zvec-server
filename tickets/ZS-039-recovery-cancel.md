---
id: ZS-039
title: Cancel recovery tasks on drop and shutdown
spec: SPEC-009
type: feature
priority: P0
status: done
release: v0.1.2
created: 2026-07-02
closed: 2026-07-08
---

# ZS-039: Cancel recovery tasks on drop and shutdown

## Summary

A SPEC-009 recovery task retries until it succeeds, so nothing else guarantees that it
ever stops. If a collection is dropped while it is still recovering, its task would
keep trying to open a directory that no longer exists. At shutdown, pending tasks
would still be sleeping on the event loop. `drop()` and `close()` must cancel them,
so that no task outlives its collection or the process.

## Acceptance criteria

- [x] `drop(name)` pops the collection's entry from `_recovery_tasks` and cancels the
      task. It does this under the manager lock, after removing the collection from
      the registry and from the metadata store.
- [x] `close()` cancels every pending task and clears `_recovery_tasks`, then runs
      `flush_all()`.
- [x] Awaiting a cancelled task raises `CancelledError`. No task retries after its
      collection is dropped or after shutdown.
- [x] Tests: with a 10 s delay pending, `close()` cancels the task. `drop("docs")`
      removes `docs` from `_recovery_tasks` and cancels the task.

## Notes

- Cancellation is cooperative. It takes effect at the task's next `await`, which is
  either the backoff sleep or the threadpool await. An `_open_record` call that is
  already running in a worker thread keeps running to completion; the coroutine just
  never resumes past the await.
- `close()` is synchronous and does not await the cancelled tasks. The event loop
  finishes them after the lifespan exits.
- `drop()` of an unavailable collection removes its directory with `rmtree`, so a task
  that ran after the drop would fail its open anyway. Cancelling keeps it from
  retrying forever.

## Resolution

Implemented in `CollectionManager.drop()` and `close()` in `manager.py`, with two unit
tests in `tests/unit/test_manager.py`. Cancellation is fire-and-forget: neither method
waits for the task to finish, and a reopen that is already running in a worker thread
is not interrupted. The new tests called `drop()` directly on the event-loop thread.
