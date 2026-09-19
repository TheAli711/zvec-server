---
id: ZS-055
title: Streaming NDJSON export endpoint
spec: SPEC-013
type: feature
priority: P1
status: done
release: v0.2.0
created: 2026-09-15
closed: 2026-09-19
---

# ZS-055: Streaming NDJSON export endpoint

## Summary

Implement `GET /collections/{name}/export` per SPEC-013: an adapter snapshot cursor
over `Collection.iter_docs`, a generic batched `ManagedCollection.stream()` that
takes the shared lock per batch only, cursor tracking so `drop()` and `close()` can
release open iterators first, and an NDJSON `StreamingResponse` with an in-band
error line for failures after streaming starts.

## Acceptance criteria

- [x] The route streams every document as `application/x-ndjson` in `DocIn` shape
      (`id`, `vectors`, `fields`; no `score`), and the output re-imports through
      `/docs/insert` unchanged.
- [x] `include_vector` (default `true`) and repeatable `output_fields` shape each
      line; an unknown field returns `400` before any body is sent; a missing
      collection returns `404`.
- [x] Empty collections return an empty body; exports larger than one batch
      (`EXPORT_BATCH_SIZE = 500`) are complete.
- [x] A write issued mid-export neither waits for the export nor appears in it.
- [x] `drop()` and `close()` call `close_cursors()` under the exclusive lock; the
      interrupted stream fails with `CollectionUnavailableError` and ends with an
      error-envelope line.
- [x] No cursor stays registered after a stream finishes, fails, or is cut off by
      drop/close.
- [x] The route appears in `docs/API.md`, the README route table,
      `docs/ARCHITECTURE.md`, `CLAUDE.md`, and `CHANGELOG.md`.

## Notes

- Adapter (`operations.py`): `open_export()` and `DocExport` (`next_batch`, `close`).
  Manager (`manager.py`): `Cursor` protocol, `stream()`, `_release_cursor()`,
  `close_cursors()`; must not import `zvec`. API (`api/vectors.py`): NDJSON framing,
  first batch read before the response so input errors are normal JSON errors.
- Never hold the shared lock across a `yield`; a slow client would block writers.
- Zvec refuses to close or destroy a collection with an open iterator, so any
  drop/close path that misses `close_cursors()` will fail. Record this as a
  `CLAUDE.md` invariant.
- Tests: `tests/integration/test_vectors_api.py` for the HTTP behaviour, and
  `tests/unit/test_manager.py` for snapshot isolation, lock release between batches,
  and drop/close mid-stream.

## Resolution

Added `open_export`/`DocExport` in the adapter, `Cursor`, `stream()`, and
`close_cursors()` in `manager.py` (called from `drop()` and `close()`), and the
`/export` route in `api/vectors.py`, with integration and unit tests. The API
reference, README route row, architecture note on export cursors, `CLAUDE.md`
invariant, and CHANGELOG entry shipped in the same change. A cursor left open when
the client disconnects mid-stream was found afterwards and fixed in ZS-065.
