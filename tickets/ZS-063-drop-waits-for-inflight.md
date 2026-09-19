---
id: ZS-063
title: Drop does not wait for in-flight requests; queued requests hit a dead handle
spec: SPEC-002
type: bug
priority: P0
status: done
release: v0.2.0
created: 2026-09-19
closed: 2026-09-19
---

# ZS-063: Drop does not wait for in-flight requests; queued requests hit a dead handle

## Summary

`CollectionManager.drop()` destroys the Zvec collection while holding only the
registry lock, never the collection's reader/writer lock. It therefore destroys the
handle under searches, writes, or an optimize that are still running. Also,
`read()`, `write()`, and `maintain()` capture the handle **before** queueing for the
lock. A request queued behind a drop, or behind shutdown's `close()` (ZS-042), then
runs against a destroyed or closed handle.

## Reproduction

1. Start a slow read on a collection, such as a large search or an optimize, which
   holds the shared lock since ZS-043.
2. While it runs, call `DELETE /collections/{name}`, then queue a write (e.g.
   `POST /collections/{name}/docs/insert`).

Observed: the drop returns at once and destroys the collection under the running
read. The queued write then runs on the handle it captured earlier, which is now
destroyed.

Expected: the drop waits for in-flight operations. Requests queued behind it, or
behind shutdown, fail with `503 collection_unavailable`, and later requests get
`404 collection_not_found`.

## Acceptance criteria

- [x] `drop()` takes the collection's exclusive lock before destroying, outside
      the registry lock, so a long optimize doesn't stall other routes.
- [x] Under that lock, drop detaches the handle and sets a new
      `ManagedCollection.dropped` flag. A second concurrent drop gets 404.
- [x] `read()`, `write()`, and `maintain()` re-resolve the handle **inside** the
      lock via `_require_open()`, and still fail fast before queueing.
- [x] A unit test covers it: drop blocks behind an in-flight read, a write queued
      behind the drop raises `CollectionUnavailableError`, and a second drop 404s.
- [x] A CHANGELOG *Fixed* entry is added.

## Notes

- Module: `manager.py` only. Any path that destroys or closes a handle must take
  the exclusive lock and detach the handle first, as `close()` already does.
- Related: background recovery must not re-attach a handle to a dropped entry
  (tracked separately against SPEC-009).

## Resolution

`drop()` now waits on the collection's exclusive lock, detaches the handle, and
marks the entry `dropped` before removing it from the registry and metadata store.
All three lock helpers now re-resolve the handle under the lock. A unit test covers
waiting, queued failure, and a double drop. A follow-up test under ZS-043 confirmed
the same behaviour when a running optimize is in flight.
