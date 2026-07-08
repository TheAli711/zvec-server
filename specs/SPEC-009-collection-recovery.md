---
id: SPEC-009
title: Self-healing recovery for unavailable collections
status: implemented
created: 2026-07-01
release: v0.1.2
---

# SPEC-009: Self-healing recovery for unavailable collections

## Summary

When a registered collection fails to open at startup, SPEC-002 keeps it in the
registry as *unavailable*, and today it stays that way until the process restarts.
This spec adds a background task for each unavailable collection. The task retries
the open with exponential backoff until it succeeds. A collection that lost a
transient race then becomes available on its own. The most common race is a rolling
restart where the previous instance still holds Zvec's on-disk lock. Two settings
control the backoff, and dropping the collection or shutting down cancels a pending
retry. The API does not change.

## Motivation

ZS-036 reports the failure. During a rolling restart the new instance starts before
the old one has released Zvec's lock on the collection directories. `load_all()`
catches the failed open, logs `Failed to open collection; marking unavailable`, and
registers the collection without a handle. After that:

- every request to the collection returns `503 collection_unavailable`;
- `GET /readyz` reports `collections_unavailable > 0`;
- nothing ever retries.

An operator has to notice and restart again, and that restart can hit the same race.
The cause is transient, because the lock is released seconds later, so the server
should recover by itself.

We considered three alternatives and rejected all of them:

- **Retry inside `get(name)` when a request hits an unavailable collection.**
  SPEC-002 makes the registry lookup an O(1), non-blocking operation. Opening a
  collection is a blocking engine call, so this would tie request latency to retry
  timing. It would also only heal collections that happen to receive traffic.
- **Block startup until every collection opens.** One stuck collection would keep the
  server and every healthy collection down. `/readyz` could also no longer report
  partial availability.
- **Crash, and let the orchestrator restart us.** This produces crash loops and
  undoes SPEC-002's rule that an unavailable collection is not fatal.

## Goals

- A collection that is unavailable at startup becomes available without a restart and
  without any client action.
- `get(name)` stays a plain O(1) lookup that never blocks and never retries.
- Retries are cheap and infrequent: exponential backoff with a configurable cap.
- No retry task outlives its collection or the process.

## Non-goals

- Coordinating with, or evicting, the process that holds the lock. We wait for the
  lock; we never break it.
- Watching collections that fail after startup. An open collection never goes back to
  unavailable today.
- Detecting or repairing corrupted collections. A permanently broken collection keeps
  retrying at the cap, logging each failure, until it is dropped.
- A retry budget or give-up threshold. We also add no admin endpoint to force a retry
  or inspect retry state. `available` on `GET /collections/{name}` and the counts on
  `/readyz` already show the outcome.
- Gating readiness. `/readyz` keeps returning `200` with counts, as in SPEC-001.
- Multiple instances sharing one data directory. This spec tolerates a short overlap
  during a restart; it does not make concurrent instances safe.

## Requirements

- **R1.** `CollectionManager.start_recovery()` must spawn one background `asyncio`
  task per unavailable collection. The app lifespan must call it once, right after
  `load_all()`.
- **R2.** Each task must sleep for the current delay and then retry the open. The
  retry must use the startup code path (`_open_record`: the missing-directory check,
  then the adapter open with the record's mmap option) and must run in the threadpool,
  never on the event loop.
- **R3.** When a retry succeeds, the task must install the handle on the existing
  `ManagedCollection` (keeping its RW lock and record), log `Recovered previously
  unavailable collection`, and exit. The collection must then serve requests
  immediately and count as loaded.
- **R4.** On failure, the delay must double, capped at the maximum. The task must keep
  retrying until it succeeds or is cancelled.
- **R5.** The delays must be configurable through two settings:
  `ZVEC_SERVER_COLLECTION_RECOVERY_INITIAL_DELAY_SECONDS` (default `30.0`) and
  `ZVEC_SERVER_COLLECTION_RECOVERY_MAX_DELAY_SECONDS` (default `300.0`).
- **R6.** There must be at most one task per collection. A finished task must remove
  itself from the manager's task table.
- **R7.** `drop(name)` must cancel that collection's pending task. `close()` must
  cancel every pending task before it flushes.
- **R8.** `get(name)` must still raise `CollectionUnavailableError` (`503`) straight
  away while a collection is recovering.
- **R9.** The manager must remain zvec-free. All engine access goes through
  `zvec_server.adapter`.

## Design

### Lifecycle

```
lifespan startup:   store.connect() → manager.load_all() → manager.start_recovery()
                    → app.state.ready = True
per unavailable collection (task "recover-<name>"):
    delay = initial
    while not managed.available:
        await asyncio.sleep(delay)
        reopened = await run_in_threadpool(manager._open_record, managed.record)
        if reopened.available:
            managed.collection = reopened.collection   # same ManagedCollection object
            log "Recovered previously unavailable collection"; return
        delay = min(delay * 2, max_delay)
lifespan shutdown:  app.state.ready = False → manager.close()
                    (cancel all recovery tasks → flush_all → clear registry)
```

With the defaults, the waits between attempts are 30, 60, 120, 240, then 300 s, so the
retries land roughly 30 s, 90 s, 210 s, 450 s, and 750 s after startup, then every
5 minutes. A 30 s first wait is meant to cover a typical container stop grace period,
so a one-off race usually clears on the first retry. The 300 s cap limits the log
noise from a collection that never recovers.

### Manager (`manager.py`)

- **Task table.** `_recovery_tasks: dict[str, asyncio.Task[None]]`.
- **`start_recovery()`.** Snapshots the registry under the manager lock, then calls
  `_spawn_recovery_task` for every entry whose `available` is false.
- **`_spawn_recovery_task(managed)`.** Does nothing if a task already exists for that
  name. Otherwise it calls `asyncio.create_task(..., name=f"recover-{name}")` and
  registers a done-callback that pops the entry.
- **`drop()`.** After the registry and metadata rows are removed, it pops the task and
  calls `task.cancel()`, still under the manager lock.
- **`close()`.** Cancels every task and clears the table, then runs `flush_all()`.

Tasks need a running event loop, so `start_recovery()` must be called from the async
lifespan, not from synchronous setup code.

### Configuration (`config.py`)

```python
collection_recovery_initial_delay_seconds: float = 30.0
collection_recovery_max_delay_seconds: float = 300.0
```

Document both settings in:

- `docs/CONFIGURATION.md`, in a new "Collection recovery" section;
- the configuration table in `README.md`;
- `.env.example`.

### Observable behaviour

While `docs` is recovering:

```
GET  /readyz → 200
     {"status":"ready","collections_loaded":2,"collections_unavailable":1}
GET  /collections/docs → 200 {"name":"docs", ..., "available":false}
POST /collections/docs/search → 503
     {"error":{"code":"collection_unavailable",
               "message":"Collection 'docs' is registered but not open.",
               "details":{"name":"docs"}}}
```

After the task succeeds, `/readyz` shows `collections_unavailable: 0` and requests
succeed. The API gains no endpoints and no fields.

## Acceptance criteria

- A collection whose directory is missing at startup and reappears shortly afterwards
  is reopened by its task without any request. `counts()` goes from `(0, 1)` to
  `(1, 0)`.
- A collection whose open keeps failing is retried until it succeeds; the task does
  not give up after one attempt.
- `close()` during a pending delay cancels the task. Awaiting the task then raises
  `CancelledError`.
- `drop()` on a collection that is still recovering removes its task entry and
  cancels the task.
- The defaults are `30.0` and `300.0`, and the environment variables override them.
  Both settings appear in `docs/CONFIGURATION.md`, `README.md`, and `.env.example`.
- While a collection is recovering, `get()` raises straight away. Startup with a
  missing directory still marks the collection unavailable instead of failing.

## Risks and open questions

- **Cancellation is cooperative.** A task stops at its next `await`. An
  `_open_record` call that is already running in a worker thread cannot be
  interrupted. The window is one open per backoff interval, but a drop that lands
  inside it needs care. We accept this for now.
- **Settings are not validated.** A zero delay, or a max below the initial delay,
  would give a hot loop or a flat schedule. Should we add bounds? The defaults are
  sane, so this is deferred.
- **Readiness.** `/readyz` stays `200` while collections recover, so an orchestrator
  may route traffic to an instance whose collection still returns 503. An opt-in
  strict readiness mode is a possible follow-up.
- **Log noise.** A collection that never recovers logs an exception every
  `max_delay`. That is a deliberate trade-off against failing silently.

## Tickets

- ZS-037 — Background recovery task with exponential backoff
- ZS-038 — Recovery delay settings and docs
- ZS-039 — Cancel recovery tasks on drop and shutdown
