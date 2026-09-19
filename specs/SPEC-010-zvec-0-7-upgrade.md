---
id: SPEC-010
title: Upgrade to Zvec 0.7.0
status: implemented
created: 2026-09-08
release: v0.2.0
---

# SPEC-010: Upgrade to Zvec 0.7.0

## Summary

Raise the server's minimum engine version from `zvec>=0.5.0` to `zvec>=0.7.0` and
adopt the two 0.7.0 behaviours that change how the server manages collections:
collection handles can be closed explicitly, and the engine keeps serving reads
while `optimize` runs. Shutdown will close every handle deliberately, and
`POST /collections/{name}/optimize` will stop blocking searches and fetches. The
REST contract does not change; clients see fewer stalls, a working mmap mode, and
faster hand-over during rolling restarts.

## Motivation

- **mmap returns empty ids (ZS-040).** With `ZVEC_SERVER_ENABLE_MMAP=true` (the
  server default), a few freshly-optimized documents come back from search with
  `"id": ""` and Zvec logs `mmap_forward_store.cc ... Failed to find target chunk`.
  The bug is in Zvec 0.5.x's forward store; ZS-040 has been parked in the backlog
  waiting on upstream. Zvec 0.7.0 (published 2026-08-26) contains the fix, so the
  default production configuration can finally return correct results.
- **Optimize stalls reads.** Today optimize runs under the collection's exclusive
  write lock (SPEC-002), so every search and fetch on that collection waits for the
  whole segment merge / index build. On large collections that is seconds to
  minutes of read downtime. Zvec 0.7.0 documents reads as safe during optimize.
- **Slow hand-over on restart.** Handles are only released when Python
  garbage-collects them or the process exits. A replacement instance in a rolling
  restart races the old one for Zvec's on-disk lock, marks the collections
  unavailable, and waits for the SPEC-009 recovery backoff (30 s initial delay) to
  retry. 0.7.0 exposes `Collection.close()`, which releases the lock at once.
- **Upstream fixes.** 0.7.0 also fixes crash recovery, filter validation, and query
  validation (`topk`, field names), and turns thread-pool CPU pinning off by
  default, which suits containers.

## Goals

- Require Zvec 0.7.0 and pass the full test suite against it on Python 3.12 and
  3.13.
- Fix the mmap empty-id bug without a server-side workaround.
- Close every collection handle explicitly and promptly on shutdown.
- Let searches and fetches proceed while `optimize` runs on the same collection.
- Keep the REST API, configuration, and on-disk layout unchanged.

## Non-goals

- Exposing new Zvec 0.7.0 surface (new index types, quantization, extra query
  parameters, grouping). Each gets its own follow-up spec.
- Running optimize in the background. The endpoint stays synchronous and returns
  when the engine finishes.
- Letting writes run during optimize. Inserts, updates, deletes, and flush still
  wait for it.
- Supporting Zvec 0.5.x alongside 0.7.x. No compatibility shims; the floor moves.
- New configuration knobs for Zvec's thread pinning or other engine defaults.

## Requirements

- **R1.** `pyproject.toml` must declare `zvec>=0.7.0`, and `uv.lock` must resolve to
  0.7.0. CI must pass (ruff, mypy, pytest) on Python 3.12 and 3.13.
- **R2.** Only `zvec_server.adapter.*` may call the new engine APIs. Closing a handle
  must go through a new adapter helper that maps engine failures to
  `ZvecOperationError`.
- **R3.** `CollectionManager.close()` must cancel recovery tasks, flush every
  collection, remove all entries from the registry, then close each open handle
  while holding that collection's **exclusive** lock, so in-flight operations finish
  first.
- **R4.** Before closing, the manager must detach the handle from its
  `ManagedCollection` (set it to `None`). Any request still holding the entry must
  then get `503 collection_unavailable`, never a call on a closed handle.
- **R5.** A failure to close one collection must be logged and must not stop the
  others from being closed or shutdown from completing.
- **R6.** Optimize must run under the collection's **shared** lock plus a
  per-collection maintenance mutex. Searches and fetches must proceed during it.
  Writes, flush, and shutdown must wait for it. Two optimize calls on the same
  collection must never overlap.
- **R7.** As today, locks must be acquired inside the worker thread
  (`run_in_threadpool`) so the event loop never blocks, and different collections
  must never block each other.
- **R8.** With mmap enabled, search results after optimize must never carry empty
  ids.
- **R9.** CHANGELOG, `CLAUDE.md`, `docs/ARCHITECTURE.md`, and the benchmark README's
  mmap caveat must describe the new version floor and locking behaviour.

## Design

### Dependency

```toml
dependencies = [
    ...
    "zvec>=0.7.0",
]
```

No adapter mapping changes are expected: the enum, schema, doc, and query mappers use
APIs that are unchanged in 0.7.0. The upgrade ticket must prove this by running the
full suite before any behaviour changes land.

### Explicit close (adapter + manager)

`adapter/collections.py` gains `close_collection(collection) -> None`, which wraps
`collection.close()` and re-raises engine errors as `ZvecOperationError`. The
handle is unusable afterwards.

`CollectionManager.close()` shutdown sequence:

1. Cancel and forget every recovery task (unchanged from SPEC-009).
2. `flush_all()` (unchanged).
3. Under the registry lock: snapshot the entries and clear the registry.
4. For each entry, take `rwlock.gen_wlock()`, swap `collection` to `None`, and call
   `close_collection` on the old handle if there was one. Log and continue on error.

Step 4 waits for any in-flight read, write, or optimize on that collection. Because
the entry now reports `available == False`, a request that still holds a reference
fails with `CollectionUnavailableError` (503).

### Reads during optimize (manager + api)

`ManagedCollection` gains `maintenance_lock: threading.Lock` and an async
`maintain(fn)` method, next to `read()` and `write()`:

```
maintain(fn):   in a worker thread
    with maintenance_lock:        # serialize optimizes on this collection
        with rwlock.gen_rlock():  # shared: reads keep flowing, writers wait
            return fn(collection)
```

The mutex is taken **before** the shared lock. A second optimize therefore waits on
the mutex instead of holding a reader slot. The optimize route changes from
`managed.write(optimize_collection)` to `managed.maintain(optimize_collection)`.

| Operation                                   | Lock                         |
| ------------------------------------------- | ---------------------------- |
| search, fetch                               | shared                       |
| insert, upsert, update, delete, flush       | exclusive                    |
| optimize                                    | maintenance mutex + shared   |
| shutdown close                              | exclusive                    |

### API

No change. `POST /collections/{name}/optimize` still returns after the engine
finishes:

```json
200 { "message": "Collection 'articles' optimized." }
```

Errors are unchanged: `404 collection_not_found`, `503 collection_unavailable`.

### Documentation

- `CHANGELOG.md` `[Unreleased]`: *Changed* for the version floor, non-blocking
  optimize, and explicit close; *Fixed* for the mmap empty-id bug.
- `CLAUDE.md` concurrency invariant and `docs/ARCHITECTURE.md` lock section: add
  `maintain()`, the maintenance mutex, and explicit close.
- `benchmarks/README.md`: the mmap caveat now says the bug is fixed in 0.7.0.

## Acceptance criteria

- `uv run pytest`, `ruff`, and `mypy` pass on Python 3.12 and 3.13 with Zvec 0.7.0.
- With mmap on, `--mmap` benchmark runs return no empty ids and recall matches
  `--no-mmap`.
- After `close()`, a second manager on the same data directory opens every
  collection straight away, with none marked unavailable. A stale reference to a
  closed entry gets `503`.
- While optimize runs, a search on the same collection completes, and a write on it
  stays pending until optimize finishes.
- Two concurrent optimize calls on one collection run one after the other.
- No request or response shape changes; the docs listed above are updated.

## Risks and open questions

- **On-disk compatibility.** We must confirm that 0.7.0 opens data directories
  written by 0.5.0. If it does not, affected collections come up `unavailable`, and
  the upgrade needs a documented re-ingest path.
- **Fair lock and mixed load.** `RWLockFair` queues a writer behind a running
  optimize, and later readers may queue behind that writer. One write during a
  long optimize can therefore still delay reads. This needs measuring under load.
- **Trusting the engine.** Shared-lock optimize depends on Zvec 0.7.0's guarantee
  that reads are safe during optimize. If a regression appears, the route can go
  back to `write()` in one line.
- **Stale references.** Anything that keeps a handle past `close()` (for example,
  a recovery task or a request queued on the lock) must re-check availability
  under the lock. New lifecycle paths must follow the same rule.
- **Version floor.** Deployments pinned to Zvec 0.5.x cannot take this release.
  The minor version bump (v0.2.0) signals this.

## Tickets

- ZS-041 — Require Zvec 0.7.0
- ZS-042 — Close collection handles explicitly on shutdown
- ZS-043 — Serve reads while optimize runs
- ZS-044 — Document the Zvec 0.7.0 upgrade, explicit close, and optimize locking
