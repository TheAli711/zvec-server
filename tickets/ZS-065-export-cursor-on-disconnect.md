---
id: ZS-065
title: Export cursor is held after the client disconnects
spec: SPEC-013
type: bug
priority: P1
status: done
release: v0.2.0
created: 2026-09-19
closed: 2026-09-19
---

# ZS-065: Export cursor is held after the client disconnects

## Summary

When a client hangs up in the middle of `GET /collections/{name}/export`, Starlette's
`StreamingResponse` stops iterating the body but never closes it. The suspended
generator chain (`_ndjson_stream` → `ManagedCollection.stream()`) keeps its Zvec
snapshot iterator open and registered in `managed.cursors` until the garbage
collector finalizes it. That breaks SPEC-013 R8 (release the cursor on every path),
and while the iterator is open Zvec rejects `optimize` on the collection.

## Reproduction

1. Insert a few documents and make batches small (e.g. `EXPORT_BATCH_SIZE = 1`) so
   the export needs several chunks.
2. Start `GET /collections/{name}/export` and disconnect after the first chunk. On
   ASGI spec 2.3 the server delivers `http.disconnect`; on 2.4 the next `send`
   raises `OSError`. Starlette handles both by abandoning the body iterator.
3. With garbage collection disabled, inspect `managed.cursors`.

Observed: the cursor is still registered and its Zvec iterator still open, for as
long as the abandoned async generator waits to be finalized by the GC.
Expected: the cursor is closed and unregistered as soon as the response ends.

## Acceptance criteria

- [x] The export response closes its body iterator (`aclose()`) whenever the
      response ends, including on client disconnect.
- [x] `_ndjson_stream` closes the underlying batch generator in a `finally`, which
      runs `stream()`'s cleanup and releases the cursor.
- [x] A test drives the ASGI app directly (TestClient buffers streams) with a client
      that disconnects after the first chunk, for ASGI spec 2.3 and 2.4, with GC
      disabled, and asserts `managed.cursors` is empty afterwards.
- [x] Existing export tests (normal completion, drop/close mid-stream) still pass.

## Notes

- Modules: `api/vectors.py` (response class, `_ndjson_stream`) and `manager.py`
  (type `stream()` as an `AsyncGenerator` so callers can `aclose()` it). Don't rely
  on `DocIterator.__del__`; Zvec documents it as a best-effort fallback.
- `_release_cursor()` already skips cursors taken by `close_cursors()`, so a
  disconnect racing a drop won't double-close.

## Resolution

Added `_ClosingStreamingResponse`, a `StreamingResponse` subclass that awaits
`body_iterator.aclose()` in a `finally`, and made `_ndjson_stream` close its batch
generator in its own `finally`. `ManagedCollection.stream()` and the helpers are now
typed as `AsyncGenerator`. Covered by `test_export_client_disconnect_releases_cursor`
in `tests/integration/test_vectors_api.py`; no separate CHANGELOG entry, as the
export endpoint had not shipped yet.
