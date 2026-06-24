# Architecture

Zvec Server is a thin, single-process HTTP layer over the
[Zvec](https://github.com/alibaba/zvec) vector database. This document describes
the module layout, the request lifecycle, the concurrency model, and how data is
persisted.

## Design principles

- **Thin layer over Zvec.** No application concepts: no tenants, workspaces,
  knowledge bases, users, or embedding generation. The server stores
  client-supplied vectors and serves them back. The only access control is an
  optional, single static API key (see [SECURITY.md](../SECURITY.md)).
- **Adapter isolation.** Only the `zvec_server.adapter.*` package is allowed to
  `import zvec`. Everything else works with plain types and Pydantic models. This
  keeps the engine dependency contained and the rest of the code testable.
- **Single process.** Collections are process-local: each is opened once at
  startup and kept in an in-memory registry. They are never opened/closed per
  request.

## Module layout

```
src/zvec_server/
├── app.py            # create_app() factory + lifespan (startup/shutdown)
├── __main__.py       # `zvec-server` console entry; runs uvicorn (workers=1)
├── config.py         # Settings (pydantic-settings, ZVEC_SERVER_ prefix)
├── errors.py         # exception types + ErrorResponse + exception handlers
├── logging.py        # configure_logging / get_logger (json|console)
├── deps.py           # FastAPI dependencies (get_manager, get_metadata)
├── manager.py        # CollectionManager + ManagedCollection (registry, locks)
├── models/           # Pydantic request/response models (no zvec)
│   ├── collections.py
│   ├── vectors.py
│   ├── search.py
│   └── common.py
├── db/
│   └── metadata.py   # MetadataStore (SQLite, WAL) + CollectionRecord
├── adapter/          # the ONLY layer that imports zvec
│   ├── runtime.py    # init_zvec() (guarded, once per process)
│   ├── enums.py      # dtype/metric/index parsing & validation
│   ├── schema_mapper.py
│   ├── doc_mapper.py
│   ├── query_mapper.py
│   ├── collections.py
│   └── operations.py # insert/delete/fetch/search over a zvec.Collection
└── api/
    ├── health.py     # GET /healthz, GET /readyz
    ├── collections.py# /collections CRUD + flush/optimize
    └── vectors.py    # /collections/{name}/docs/* and /search
```

### Import direction (layering)

```
api      ->  manager, models, adapter, errors, deps, config
manager  ->  adapter, db, models, errors, config
adapter  ->  enums, errors, models   (and zvec)
db       ->  stdlib only
models   ->  pydantic only
config, errors, logging, enums  ->  leaf modules
```

The `api` and `manager` layers never import `zvec`; only `adapter` does.

## Application startup & shutdown

`create_app(settings=None)` builds the FastAPI app and wires a `lifespan`:

**Startup**

1. `configure_logging(level, format)`.
2. `init_zvec(...)` — initialize the Zvec engine exactly once per process
   (guarded so multiple apps in one process, e.g. tests, are safe).
3. `settings.ensure_directories()` — create the data, collections, and metadata
   directories.
4. `MetadataStore(...).connect()` — open SQLite (WAL mode), create/migrate the
   schema.
5. `CollectionManager(...).load_all()` — for each recorded collection, open it
   from disk and register it; if its directory is missing, it is marked
   **unavailable** (kept in the registry so `info` can report `available=false`).
6. Store the manager and store on `app.state`; set `app.state.ready = True`.

**Shutdown**

1. `manager.close()` — flush every open collection.
2. `store.close()` — close the SQLite connection.

## Request lifecycle

```
HTTP request
  → FastAPI router (api/, async)
  → resolve CollectionManager via Depends(get_manager)
  → manager.get(name) → ManagedCollection (O(1) registry lookup)
  → managed.read(fn) / managed.write(fn)
        └─ run_in_threadpool:
              with rwlock.gen_rlock() / gen_wlock():
                  adapter.<operation>(collection, ...)   # the only zvec call
  → adapter returns Pydantic models
  → router serializes the response
```

Errors raised by the adapter/manager are mapped to HTTP responses by the
exception handlers registered in `errors.py` (e.g. `CollectionNotFoundError` →
404, `InvalidArgumentError` → 400, validation → 422).

## Concurrency model

- **Per-collection reader/writer lock.** Each `ManagedCollection` owns a fair
  `RWLockFair` (`readerwriterlock`). Reads (`fetch`, `search`) take a shared read
  lock; writes (`insert`/`upsert`/`update`/`delete`, `flush`, `optimize`) take an
  exclusive write lock. Different collections never block each other.
- **Threadpool offload.** Zvec calls are blocking/CPU-bound, so they run inside
  `starlette.concurrency.run_in_threadpool`. The lock is acquired **inside** the
  threadpool thread, so the asyncio event loop is never blocked waiting on a
  lock.
- **Single worker / single process.** Because the registry of open collections
  lives in process memory, the server runs with **one** uvicorn worker. Running
  multiple workers against the same data directory is unsafe (each would open the
  same on-disk collection independently). To scale, run separate single-worker
  instances that target **distinct** data directories, fronted by a router.

## Persistence model

There are two stores, with a strict division of responsibility:

- **Zvec engine** (under `COLLECTIONS_DIR`, one directory per collection): holds
  the vectors and the **scalar fields used for filtering and output**. All
  similarity search, filtering, fetch, and document CRUD go through Zvec.
- **SQLite metadata DB** (`metadata.db`, WAL mode): holds **only** collection
  metadata — the `CollectionRecord` rows: name, on-disk path, schema version,
  primary vector name, dimension, metric, index type, serialized
  schema/options JSON, and `created_at` / `updated_at` timestamps. It never
  stores vectors, document fields, or text.

This separation means the metadata DB stays tiny and authoritative for "what
collections exist", while Zvec remains the source of truth for the actual vector
data. On restart, `load_all()` reconciles the two: it reads the records from
SQLite and reopens each collection's directory from disk.
