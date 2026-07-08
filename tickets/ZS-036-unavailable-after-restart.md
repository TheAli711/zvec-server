---
id: ZS-036
title: Collections stay unavailable after a rolling restart
spec: SPEC-002
type: bug
priority: P0
status: done
release: v0.1.2
created: 2026-06-30
closed: 2026-07-08
---

# ZS-036: Collections stay unavailable after a rolling restart

## Summary

During a rolling restart, the new instance can start while the old one still holds
Zvec's on-disk lock on the collection directories. `load_all()` handles the failed
open as SPEC-002 intends and registers the collection as unavailable instead of
crashing. After that, nothing ever retries the open. The collection returns `503` for
every request until someone restarts the server, and that restart can hit the same
race. This is P0 because a routine deploy can silently take collections offline.

## Reproduction

1. Run instance A on a data directory that contains a collection named `docs`.
2. Start instance B on the same directory before A has fully exited. For example, a
   rolling update over a shared volume that starts the replacement first.
3. B logs `Failed to open collection; marking unavailable` for `docs`, then
   `Loaded collections` with `loaded=0, unavailable=1`.
4. A finishes shutting down and releases the lock.
5. On B, these responses never change:

```
GET  /readyz → 200 {"status":"ready","collections_loaded":0,"collections_unavailable":1}
GET  /collections/docs → 200 {"name":"docs", ..., "available":false}
POST /collections/docs/search → 503 {"error":{"code":"collection_unavailable", ...}}
```

Expected: once A releases the lock, B opens `docs` on its own. Actual: `docs` stays
unavailable until B is restarted.

## Acceptance criteria

- [x] A collection that failed to open at startup becomes available without a restart
      once the cause clears.
- [x] No request is needed to trigger the retry, and no request blocks waiting for
      it.
- [x] Startup still succeeds when a collection cannot be opened.
- [x] A regression test simulates a transient outage at startup and asserts that the
      collection reopens.

## Notes

- Root cause: in SPEC-002 "unavailable" is terminal for the process lifetime;
  `manager.py` has no retry path. Retrying inside `get()` would break its O(1),
  non-blocking contract, so the fix needs its own design: SPEC-009.
- Workaround until the fix ships: restart B after A has fully exited, and have the
  orchestrator stop the old instance before starting the new one.

## Resolution

Fixed by SPEC-009, shipped in v0.1.2. `CollectionManager.start_recovery()` now
retries each unavailable collection in the background with exponential backoff
(ZS-037, ZS-038, ZS-039). The regression test in `tests/unit/test_manager.py` moves
the collection directory aside at startup and restores it after the first retry.
