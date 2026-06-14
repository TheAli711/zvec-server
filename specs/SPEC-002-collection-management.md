---
id: SPEC-002
title: Collection management and metadata store
status: draft
created: 2026-06-14
release: v0.1.0
---

# SPEC-002: Collection management and metadata store

## Summary

Let clients create, list, inspect, drop, flush, and optimize Zvec collections over
HTTP. A collection is defined by one or more vector fields and optional scalar
fields; the server translates that schema into Zvec's native types, creates the
collection on disk, records lightweight metadata in SQLite, and keeps every
collection open in an in-memory registry for the life of the process. Builds on
SPEC-001 (app factory, settings, error envelope, readiness counts).

## Motivation

Collections are the unit everything else operates on: document writes, fetches,
and search all name a collection. Zvec needs a native `CollectionSchema`, a data
directory, and an open handle per collection. Opening a collection is too costly to
do per request, and the server must remember which collections exist across
restarts without re-deriving it from directory names. We also need a concurrency
model before any document endpoint exists, because Zvec calls are blocking and the
HTTP layer is async.

## Goals

- A JSON schema format covering Zvec's vector dtypes, scalar dtypes, index types
  (`hnsw`, `flat`, `ivf`), and metrics, with friendly defaults.
- A durable, tiny metadata store that answers "which collections exist".
- Open each collection once at startup; resolve it per request in O(1).
- Reads on a collection run concurrently; writes are exclusive; collections never
  block each other; the event loop never blocks.
- A missing or broken collection must not prevent the server from starting.
- Keep Zvec behind an adapter: only `zvec_server.adapter.*` imports `zvec`.

## Non-goals

- Altering a collection's schema after creation (add/drop/rename fields), renaming
  collections, or aliases.
- Storing vectors, document fields, or text in SQLite.
- Sharing one data directory between processes or Uvicorn workers.
- Automatically re-opening an unavailable collection while the server runs; the
  operator fixes the data and restarts.
- Asynchronous job tracking for long operations; `optimize` is synchronous.
- Per-collection access control or tenancy.

## Requirements

- **R1.** `POST /collections` must create a collection from a
  `CreateCollectionRequest` and return `201` with `CollectionInfo`.
- **R2.** Names must match `^[A-Za-z0-9_-]{1,128}$` (they become directory names);
  at least one vector field is required and `dim` must be > 0. Violations → `422
  validation_error`.
- **R3.** Unknown dtypes, metrics, or index types, a scalar dtype used for a vector
  (or vice versa), and non-integer index params → `422 schema_validation_error`
  with the valid values in `details.valid` where applicable.
- **R4.** Creating an existing name → `409 collection_already_exists`.
- **R5.** If persisting metadata fails after the on-disk collection was created,
  the collection must be destroyed again (no orphans).
- **R6.** `GET /collections` lists every registered collection with summary data;
  `GET /collections/{name}` returns the full schema snapshot, options, live stats,
  and an `available` flag. Unknown name → `404 collection_not_found`.
- **R7.** `DELETE /collections/{name}` removes the data on disk, the metadata row,
  and the registry entry, including for unavailable collections.
- **R8.** `POST /collections/{name}/flush` and `/optimize` persist buffered writes
  and run index optimization respectively, returning a `MessageResponse`.
- **R9.** At startup every metadata record is opened once. A missing directory or
  open failure marks the collection *unavailable* (kept in the registry) instead
  of failing startup. Document operations, flush, and optimize on it → `503
  collection_unavailable`; info and drop still work.
- **R10.** Each collection has a fair reader/writer lock; blocking engine calls run
  in a threadpool with the lock acquired inside the worker thread.
- **R11.** Shutdown flushes every open collection (best effort) and closes SQLite.
- **R12.** SQLite runs in WAL mode, is safe to share across threadpool threads, and
  carries a schema version for future migrations.

## Design

### Endpoints

```
POST   /collections                  201 CollectionInfo
GET    /collections                  200 {"collections": [CollectionSummary]}
GET    /collections/{name}           200 CollectionInfo
DELETE /collections/{name}           200 {"message": "Collection 'articles' deleted."}
POST   /collections/{name}/flush     200 {"message": "Collection 'articles' flushed."}
POST   /collections/{name}/optimize  200 {"message": "Collection 'articles' optimized."}
```

Create request (defaults: `dtype=VECTOR_FP32`, `index=hnsw`, `metric=cosine`,
`nullable=false`, `indexed=false`):

```json
{
  "name": "articles",
  "vectors": [{"name": "embedding", "dim": 768, "dtype": "VECTOR_FP32",
               "index": "hnsw", "metric": "cosine",
               "params": {"m": 16, "ef_construction": 200}}],
  "fields": [{"name": "category", "dtype": "STRING", "indexed": true},
             {"name": "year", "dtype": "INT64", "indexed": true}],
  "options": {"enable_mmap": true},
  "embedding_model": "text-embedding-3-small"
}
```

`CollectionInfo` response:

```json
{
  "name": "articles", "path": "/data/collections/articles", "schema_version": 1,
  "embedding_dimension": 768, "embedding_model": "text-embedding-3-small",
  "vectors": [{"name": "embedding", "data_type": "VECTOR_FP32", "dimension": 768}],
  "fields": [{"name": "category", "data_type": "STRING", "nullable": false}],
  "options": {"enable_mmap": true},
  "stats": {"doc_count": 0, "index_completeness": {}},
  "available": true,
  "created_at": "2026-06-23T10:00:00+00:00", "updated_at": "2026-06-23T10:00:00+00:00"
}
```

`vectors`/`fields` are Zvec's own serialization of the created schema. For an
unavailable collection, `stats` is `null` and `available` is `false`; in the list,
`doc_count` is `null`. `embedding_model` is a free-form label only.

### Schema mapping (adapter)

- Vector dtypes: `VECTOR_FP16|FP32|FP64|INT8`, `SPARSE_VECTOR_FP16|FP32`. Scalar
  dtypes: `INT32|INT64|UINT32|UINT64|FLOAT|DOUBLE|STRING|BOOL` and `ARRAY_*`.
  Parsing is case-insensitive.
- Metrics: `cosine`, `ip`, `l2`, with aliases `dot`/`inner_product` → `IP` and
  `euclidean` → `L2`.
- `hnsw` → `HnswIndexParam(m, ef_construction)`; `ivf` → `IVFIndexParam(n_list,
  n_iters)`; `flat` → `FlatIndexParam`. Params must be ints (bools rejected).
- `indexed: true` on a scalar attaches an `InvertIndexParam` for fast filtering.
- `options.enable_mmap` overrides `ZVEC_SERVER_ENABLE_MMAP` per collection.
- The first vector field is the *primary* vector, denormalized into metadata.

### Metadata store

`db/metadata.py`, stdlib `sqlite3`, one long-lived connection
(`check_same_thread=False`) guarded by a `threading.Lock`:

```sql
CREATE TABLE IF NOT EXISTS collections (
  name TEXT PRIMARY KEY, path TEXT NOT NULL, schema_version INTEGER NOT NULL,
  embedding_dimension INTEGER, embedding_model TEXT, primary_vector TEXT,
  metric TEXT, index_type TEXT, options_json TEXT NOT NULL,
  schema_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)
```

`PRAGMA journal_mode=WAL`; migrations keyed off `PRAGMA user_version`
(`SCHEMA_VERSION = 1`). API: `connect`, `close`, `add` (PK conflict → 409),
`get`, `list` (ordered by name), `delete`, `touch`. Timestamps are UTC ISO 8601.

### Registry and concurrency

`manager.py` holds `CollectionManager` (registry `dict[str, ManagedCollection]`
plus a `threading.Lock` for registry mutations) and `ManagedCollection` (name,
opaque handle or `None`, record, `RWLockFair`). `get(name)` is a plain lookup that
raises 404/503 immediately. `read(fn)`/`write(fn)` run `fn(handle)` via
`run_in_threadpool` under a shared/exclusive lock taken inside the worker thread.
Flush and optimize take the exclusive lock. Create and drop run in the threadpool
under the registry lock.

Layering: `api/collections.py` → `manager.py` → `adapter/collections.py`,
`adapter/schema_mapper.py`, `adapter/enums.py` → `zvec`; `manager.py` → `db`.
Engine exceptions become `ZvecOperationError` (500) in the adapter.

## Acceptance criteria

- Creating the example collection returns `201`, `available: true`,
  `stats.doc_count == 0`, `embedding_dimension == 768`; a second create → `409`.
- `name: "bad name!"` → `422`; `dtype: "NOPE"` or `"STRING"` on a vector → `422
  schema_validation_error`.
- The collection appears in `GET /collections` and `GET /collections/{name}`;
  unknown names → `404 collection_not_found`.
- After a restart against the same data dir, the collection is open again and
  `/readyz` reports it loaded.
- Deleting a collection's directory and restarting yields `collections_unavailable
  == 1`, `GET /collections/{name}` with `available: false`, and `503` on use.
- `DELETE` removes the directory; a following `GET` → `404`.
- Flush and optimize return `200` on an existing collection.

## Risks and open questions

- `optimize` holds the exclusive lock for its full duration, blocking reads and
  writes on that collection, and the HTTP request stays open until it finishes.
- Drop is serialized by the registry lock but not by the collection's own lock; a
  request already in flight on that collection may race the destroy. Acceptable
  for v0.1.0; revisit if it produces errors in practice.
- Create holds the registry lock while Zvec creates files, so concurrent creates
  (and list snapshots) serialize behind a slow create.
- The stored schema snapshot uses Zvec's serialization shape, which may change
  between Zvec versions; `schema_version` leaves room to migrate.
- Zvec may impose naming or path rules beyond our regex; such engine rejections
  flow through the create error mapping.
- Nothing bumps `updated_at` after creation yet; `touch()` exists for later use.
