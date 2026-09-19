---
id: SPEC-013
title: Streaming NDJSON export
status: implemented
created: 2026-09-13
release: v0.2.0
---

# SPEC-013: Streaming NDJSON export

## Summary

Add `GET /collections/{name}/export`, which streams **every** document of a
collection as NDJSON (`application/x-ndjson`, one JSON object per line). Each line is
shaped like a `DocIn` — `id`, `vectors`, `fields`, no `score` — so an export can be
posted back to `/docs/insert` in batches unchanged. The export is a consistent
snapshot as of the request, and it must not block writes while it streams.

## Motivation

There is no way to get documents *out* of the server in bulk. Fetch needs ids the
client may not have, and search is approximate and capped at `topk`. Backups,
migrations to a new schema or index type (e.g. trying SPEC-011's quantized indexes on
a copy), and re-indexing all need a full dump. Today that means stopping the server
and copying the Zvec directory, which ties the backup to Zvec's on-disk format and
the exact engine version.

Zvec 0.7.0 (SPEC-010) provides `Collection.iter_docs`, a snapshot iterator: writes
made after it opens are invisible to it, and it streams with constant memory. That
lets the server offer a consistent export without holding the collection lock for
the whole transfer.

## Goals

- A single `GET` that dumps a whole collection in a line-oriented, re-importable
  format usable with `curl > file`.
- A consistent snapshot, regardless of concurrent writes.
- Writes (and other reads) keep flowing during a long export to a slow client.
- Exports never prevent `drop` or shutdown from completing.

## Non-goals

- An import endpoint. Re-import uses the existing `/docs/insert` (or `upsert`).
- Filtered or partial exports (no `filter`, id range, or limit). `output_fields` and
  `include_vector` only shape each line.
- Resumable or paginated exports (offsets, continuation tokens). A failed export is
  simply restarted.
- Other formats (CSV, Parquet, binary vectors) or server-side compression; put a
  compressing proxy in front if needed.
- Exporting collection metadata or schema; `GET /collections/{name}` already returns
  it.
- Any ordering guarantee.
- File-level snapshots or backups of Zvec's on-disk data.

## Requirements

- **R1.** The server must expose `GET /collections/{name}/export` returning `200`
  with media type `application/x-ndjson`: one JSON object per line, each serialized
  from `DocOut` with `score` excluded and null members omitted, i.e. `{"id",
  "vectors", "fields"}` in `DocIn` shape.
- **R2.** Query parameters: `include_vector` (bool, default `true`, since vectors are
  needed to re-import) and `output_fields` (repeatable string, default all scalar
  fields).
- **R3.** The export must reflect the collection as of the request. Documents
  written after it starts are not included.
- **R4.** The shared lock must be held only while opening the cursor and while
  reading each batch — never across a `yield` to the client — so a slow client
  cannot block writers. Batch size is a module constant (`EXPORT_BATCH_SIZE = 500`
  documents per lock acquisition).
- **R5.** Input errors must be reported as normal JSON errors before any body is
  sent: the handler reads the first batch before returning the response. An unknown
  `output_fields` entry returns `400 invalid_argument`, a missing collection `404`,
  an unavailable one `503`.
- **R6.** If the export fails after streaming has begun (collection dropped, server
  shutting down, engine error), the stream must end with one final line holding the
  standard error envelope `{"error": {"code", "message", "details"}}` built by
  `build_error_payload`. The status stays `200`; clients must check the last line.
- **R7.** Zvec refuses to close or destroy a collection while an iterator is open.
  The manager must therefore track open cursors per collection, and `drop()` and
  `close()` must close them (`close_cursors()`) under the exclusive lock before
  destroying or closing the handle. The interrupted stream's next batch then raises
  `CollectionUnavailableError`, which R6 turns into the final error line.
- **R8.** A cursor must be released exactly once on every path: exhaustion, error,
  the consumer stopping early, or `close_cursors()` having already closed it.
- **R9.** An export must round-trip: its lines, posted to `/docs/insert` on a
  collection with the same schema, recreate the same ids, fields, and vectors.
- **R10.** Layering: only the adapter touches Zvec; the manager's streaming
  primitive is generic over a cursor protocol and never imports `zvec`; NDJSON
  framing lives in the API layer.
- **R11.** The route requires the API key when auth is enabled. The group-by route
  added by SPEC-012 lacks an auth test as well; both get one.
- **R12.** Document the endpoint in `docs/API.md`, the README route table and key
  features, `docs/ARCHITECTURE.md`, `CLAUDE.md` (the new cursor invariant),
  `CHANGELOG.md`, and both examples.

## Design

### Endpoint

```bash
curl -s localhost:8000/collections/articles/export > articles.ndjson
curl -s 'localhost:8000/collections/articles/export?include_vector=false&output_fields=year'
```

```
{"id":"a1","vectors":{"embedding":[0.1,0.2,0.3,0.4]},"fields":{"category":"tech","year":2021}}
{"id":"a2","vectors":{"embedding":[0.2,0.1,0.0,0.9]},"fields":{"category":"news","year":2019}}
{"error":{"code":"collection_unavailable","message":"Collection 'articles' was closed or dropped during the stream.","details":{"name":"articles"}}}
```

The last line above appears only when the export is cut short. An empty collection
returns `200` with an empty body.

### Layers

- **adapter** (`adapter/operations.py`): `open_export(collection, output_fields,
  include_vector) -> DocExport`. It calls `collection.iter_docs(...)` (a `ValueError`
  becomes `InvalidArgumentError`, anything else `ZvecOperationError`). `DocExport`
  wraps the Zvec iterator with `next_batch(size) -> list[DocOut]` (an empty list
  means exhausted; read errors become `ZvecOperationError`) and an idempotent
  `close()`.
- **manager** (`manager.py`): a `Cursor[T]` protocol (`next_batch`, `close`) and
  `ManagedCollection.stream(open_cursor, batch_size) -> AsyncIterator[list[T]]`.
  - Open: in a threadpool worker, under the shared lock, re-check the handle is
    open, call `open_cursor(collection)`, and add the cursor to
    `ManagedCollection.cursors` (guarded by its own small mutex).
  - Each batch: in a worker, under the shared lock, verify the cursor is still in
    `cursors` (otherwise raise `CollectionUnavailableError`), then `next_batch`.
  - `finally`: `_release_cursor()` closes the cursor unless `close_cursors()` has
    already taken it.
  - `close_cursors()` swaps the set out and closes each cursor, logging failures.
    `CollectionManager.drop()` and `close()` call it under `gen_wlock()` before
    `destroy_collection` / `close_collection`.
- **api** (`api/vectors.py`): `export_docs` resolves the collection, calls
  `managed.stream(lambda c: operations.open_export(c, output_fields,
  include_vector), EXPORT_BATCH_SIZE)`, awaits the first batch (R5), and returns a
  `StreamingResponse` over an async generator that renders each batch as
  `model_dump_json(exclude={"score"}, exclude_none=True) + "\n"` per document and
  catches `ZvecServerError` to emit the in-band error line (R6). OpenAPI documents
  the `application/x-ndjson` response.

### Concurrency

Writers are never starved by an export: between batches the export holds no lock,
and the fair RW lock lets a queued writer in. Consistency comes from the Zvec
snapshot, not from the lock. `optimize` takes only the shared lock (SPEC-010), so the
lock does not order it against exports; see the maintenance risk below.

## Acceptance criteria

- An export of a seeded collection returns every id once, with
  `content-type: application/x-ndjson`, and each line has exactly the keys `id`,
  `vectors`, `fields`.
- Posting the lines to `/docs/insert` on a new collection with the same schema
  restores the same fields and vectors.
- `include_vector=false&output_fields=year` yields lines without `vectors` and with
  only `year` in `fields`.
- An empty collection yields `200` with an empty body; a collection larger than one
  batch is exported completely.
- Unknown `output_fields` returns `400 invalid_argument`; a missing collection `404`.
- A write issued mid-export completes without waiting for the export and does not
  appear in it; afterwards no cursor remains registered.
- Dropping or closing a collection mid-export succeeds; the stream then fails with
  `CollectionUnavailableError` and no cursor remains.
- The export and group-by routes return `401` without a valid API key.

## Risks and open questions

- **In-band errors.** A `200` status no longer proves a complete export. We document
  the final error line and show the check in the Python example.
- **Maintenance while exporting.** Zvec rejects `optimize` and schema changes while
  an iterator is open, so an optimize issued during a long export can fail. We do not
  queue it behind exports; clients schedule maintenance around exports.
- **Segment churn.** On a writable collection each snapshot seals the current
  writing segment, so frequent exports can leave many small segments until the next
  optimize.
- **Abandoned streams.** A slow or vanished client keeps its snapshot open. The
  cursor must be released as soon as the consumer goes away (R8); we need to confirm
  how the ASGI server surfaces a client disconnect to the streaming generator.
- **Payload size.** Vectors dominate the output as JSON arrays; exports of large,
  high-dimensional collections are slow and large. Acceptable for a backup path.

## Tickets

- ZS-055 — Streaming NDJSON export endpoint
- ZS-056 — Auth coverage for the export and group-by routes
- ZS-057 — Document streaming export
