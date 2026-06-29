# Zvec Server

[![CI](https://github.com/TheAli711/zvec-server/actions/workflows/ci.yml/badge.svg)](https://github.com/TheAli711/zvec-server/actions/workflows/ci.yml)
[![Release](https://github.com/TheAli711/zvec-server/actions/workflows/release.yml/badge.svg)](https://github.com/TheAli711/zvec-server/actions/workflows/release.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![GHCR](https://img.shields.io/badge/ghcr.io-theali711%2Fzvec--server-blue?logo=docker)](https://github.com/TheAli711/zvec-server/pkgs/container/zvec-server)

A lightweight, storage-focused HTTP server for the
[Zvec](https://github.com/alibaba/zvec) vector database. It exposes a clean REST
API over Zvec so applications can store and search vectors without embedding the
Zvec library in-process.

## What it is

- A **thin storage layer** over Zvec, served over HTTP/JSON via FastAPI.
- A way to manage **collections** (schemas of vector + scalar fields), write
  documents (insert/upsert/update/delete), fetch by id, and run vector
  **similarity search** with SQL-like filters.
- A single-process service with first-class OpenAPI docs (`/docs`, `/redoc`).

## What it is NOT

- **Not** an embedding service. The server stores **client-supplied vectors
  only** — it does not call models or generate embeddings for you.
- **Not** an application platform. There is no multi-tenancy, no users,
  workspaces, or knowledge-base concepts. Authentication is limited to an
  optional **single static API key** (no roles, sessions, or JWTs).
- **Not** hardened for direct internet exposure. Even with the API key enabled,
  deploy it behind TLS and a trusted network or gateway (see
  [SECURITY.md](./SECURITY.md)).

## Key features

- REST API for collection lifecycle, document CRUD, fetch, and vector search.
- Multiple vector dtypes (`VECTOR_FP32`, `VECTOR_FP16`, `VECTOR_FP64`,
  `VECTOR_INT8`, sparse variants) and scalar field types.
- Index types `hnsw` / `flat` / `ivf` and metrics `cosine` / `ip` / `l2`.
- SQL-like filtering on scalar fields for search and delete.
- Optional **API-key authentication** (`Authorization: Bearer`), off by default
  and configured entirely via the environment.
- Per-collection reader/writer locking with blocking work offloaded to a
  threadpool, so the event loop stays responsive.
- Structured JSON (or human-readable console) logging; configurable via env.
- Container-ready: multi-stage `Dockerfile`, `docker-compose.yml`, and
  versioned, production images published to GHCR
  (`ghcr.io/theali711/zvec-server`) on every release.

## Quickstart

### Run locally with uv

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
# 1. Install dependencies (creates .venv)
uv sync

# 2. (optional) configure via .env
cp .env.example .env

# 3. Run the server (console entry point)
uv run zvec-server
# ...or run uvicorn directly with the app factory:
uv run uvicorn zvec_server.app:create_app --factory --host 0.0.0.0 --port 8000
```

The server listens on `http://0.0.0.0:8000` and persists data under `./data`.
Interactive API docs are available at `http://localhost:8000/docs`.

### Run with Docker (published image)

Production images are published to the GitHub Container Registry (GHCR) on every
release — no need to build from source. Pull a **specific version** (recommended
for production so deployments are reproducible):

```bash
docker pull ghcr.io/theali711/zvec-server:v0.1.0
```

Available tags for `ghcr.io/theali711/zvec-server`:

| Tag        | Points to                                          | Example  |
| ---------- | -------------------------------------------------- | -------- |
| `vX.Y.Z`   | An exact release (immutable once published).       | `v0.1.0` |
| `vX.Y`     | The latest patch on a major/minor line.            | `v0.1`   |
| `latest`   | The most recent **stable** release (no pre-releases). | `latest` |

Run the server with a mounted data volume (so collections and the SQLite
metadata DB survive container restarts) and configuration via environment
variables:

```bash
docker run -d \
  --name zvec-server \
  -p 8000:8000 \
  -v "$(pwd)/data:/data" \
  -e ZVEC_SERVER_LOG_FORMAT=console \
  -e ZVEC_SERVER_AUTH_ENABLED=true \
  -e ZVEC_SERVER_API_KEY="$(openssl rand -hex 32)" \
  ghcr.io/theali711/zvec-server:v0.1.0
```

The image stores all state under `/data` (its `ZVEC_SERVER_DATA_DIR`); the
`-v` flag bind-mounts the host's `./data` there. Any `ZVEC_SERVER_*` setting from
[Configuration](#configuration) can be passed with `-e`. The image runs as a
non-root user with a single Uvicorn worker (see the
[architecture notes](#architecture-overview)) and ships a `/healthz`
healthcheck. Verify it is up:

```bash
curl http://localhost:8000/healthz   # {"status":"ok"}
```

### Run with Docker Compose

```bash
docker compose up --build
```

This builds the image from source, mounts `./data` for persistence, and exposes
the server on `http://localhost:8000`. To run the published image instead of
building, set `image: ghcr.io/theali711/zvec-server:v0.1.0` and drop the `build:`
section in `docker-compose.yml`.

### Smoke test

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

Then walk through the full flow with the
[Python client](./examples/python_client.py) or
[curl script](./examples/curl_examples.sh) in [`examples/`](./examples).

## REST API reference

Base URL: `http://localhost:8000`. All request/response bodies are JSON. See
[docs/API.md](./docs/API.md) for full request/response shapes and examples.

### Health

| Method | Path        | Purpose                                                   |
| ------ | ----------- | --------------------------------------------------------- |
| GET    | `/healthz`  | Liveness probe. Returns `{"status":"ok"}`.                |
| GET    | `/readyz`   | Readiness probe with counts of loaded/unavailable collections. |

### Collections

| Method | Path                          | Purpose                                            |
| ------ | ----------------------------- | -------------------------------------------------- |
| POST   | `/collections`                | Create a collection (201). Body: `CreateCollectionRequest`. |
| GET    | `/collections`                | List collections.                                  |
| GET    | `/collections/{name}`         | Get collection info + live stats.                  |
| DELETE | `/collections/{name}`         | Drop a collection (deletes its data on disk).      |
| POST   | `/collections/{name}/flush`   | Flush pending writes to disk.                      |
| POST   | `/collections/{name}/optimize`| Optimize indexes for the collection.               |

### Documents

All document routes are under `/collections/{name}`.

| Method | Path                                  | Purpose                                                |
| ------ | ------------------------------------- | ------------------------------------------------------ |
| POST   | `/collections/{name}/docs/insert`     | Insert documents. Body: `WriteRequest`.                |
| POST   | `/collections/{name}/docs/upsert`     | Upsert documents. Body: `WriteRequest`.                |
| POST   | `/collections/{name}/docs/update`     | Update documents. Body: `WriteRequest`.                |
| POST   | `/collections/{name}/docs/delete`     | Delete by `ids` **or** `filter` (exactly one). Body: `DeleteRequest`. |
| POST   | `/collections/{name}/docs/fetch`      | Fetch documents by ids. Body: `FetchRequest`.          |
| GET    | `/collections/{name}/docs/{doc_id}`   | Fetch one document by id (404 if missing). Query: `include_vector`, `output_fields`. |
| POST   | `/collections/{name}/search`          | Vector similarity search. Body: `SearchRequest`.       |

> **Filters use Zvec's SQL-like syntax**, e.g. `category = 'tech' AND year > 2020`.
> Use single `=` (not `==`), single-quote string literals, and operators
> `AND` / `OR` / `NOT` / `IN` / `BETWEEN` / `LIKE`. The `filter` string is passed
> through to Zvec verbatim. See [docs/API.md](./docs/API.md#filter-syntax).

## Configuration

All variables use the `ZVEC_SERVER_` prefix and can be set via environment or a
`.env` file. Full details in [docs/CONFIGURATION.md](./docs/CONFIGURATION.md).

| Variable                            | Type          | Default                      | Description                                              |
| ----------------------------------- | ------------- | ---------------------------- | -------------------------------------------------------- |
| `ZVEC_SERVER_DATA_DIR`              | path          | `./data`                     | Root directory for all server data.                      |
| `ZVEC_SERVER_METADATA_DB_PATH`      | path          | `<data_dir>/metadata.db`     | SQLite metadata DB path.                                 |
| `ZVEC_SERVER_COLLECTIONS_DIR`       | path          | `<data_dir>/collections`     | Root directory for collection data.                      |
| `ZVEC_SERVER_HOST`                  | str           | `0.0.0.0`                    | Bind address.                                            |
| `ZVEC_SERVER_PORT`                  | int           | `8000`                       | Bind port.                                               |
| `ZVEC_SERVER_LOG_LEVEL`             | str           | `INFO`                       | `DEBUG` / `INFO` / `WARNING` / `ERROR`.                  |
| `ZVEC_SERVER_LOG_FORMAT`            | str           | `json`                       | `json` or `console`.                                     |
| `ZVEC_SERVER_ENABLE_MMAP`           | bool          | `true`                       | Enable memory-mapped storage for collections.           |
| `ZVEC_SERVER_ZVEC_MEMORY_LIMIT_MB`  | int \| null   | auto                         | Soft memory cap for the Zvec engine (MB).               |
| `ZVEC_SERVER_ZVEC_QUERY_THREADS`    | int \| null   | auto                         | Zvec query thread count.                                 |
| `ZVEC_SERVER_ZVEC_OPTIMIZE_THREADS` | int \| null   | auto                         | Zvec optimize thread count.                              |
| `ZVEC_SERVER_ZVEC_LOG_DIR`          | path \| null  | none                         | Directory for Zvec engine logs.                          |
| `ZVEC_SERVER_AUTH_ENABLED`          | bool          | `false`                      | Require an API key on every request (except health probes). |
| `ZVEC_SERVER_API_KEY`               | str \| null   | none                         | Expected bearer key. Required when auth is enabled.      |

## Authentication

Authentication is **off by default**. To require an API key, set:

```bash
ZVEC_SERVER_AUTH_ENABLED=true
ZVEC_SERVER_API_KEY="$(openssl rand -hex 32)"
```

With auth enabled, every request except `/healthz` and `/readyz` must send the
key as a bearer token:

```bash
curl http://localhost:8000/collections \
  -H "Authorization: Bearer $ZVEC_SERVER_API_KEY"
```

Missing or invalid credentials return `401 Unauthorized`. This is a deliberately
minimal, stateless mechanism (a single static key — no users, roles, or
sessions) meant to pair with externally managed secrets (Docker/Kubernetes
secrets, cloud secret managers). It is implemented as a pluggable
`AuthProvider` + middleware in `zvec_server.auth`, leaving room for richer
schemes later. See [docs/CONFIGURATION.md](./docs/CONFIGURATION.md#authentication)
and [SECURITY.md](./SECURITY.md).

## Architecture overview

```
HTTP client
    │  JSON over REST
    ▼
FastAPI routers (api/)          ── async; never import zvec
    │
    ▼
CollectionManager (manager.py)  ── in-memory registry of open collections;
    │                              per-collection RW lock; threadpool offload
    ├──▶ adapter/ (the ONLY layer that imports zvec)
    │       └──▶ Zvec engine  ── stores vectors + scalar fields (for filtering)
    └──▶ db/metadata.py (SQLite, WAL) ── stores ONLY collection metadata
```

- **CollectionManager** keeps an in-memory registry of collections, each opened
  once at startup and reused for every request — never opened/closed per call.
- **SQLite** persists *only* collection metadata (name, path, schema, timestamps).
  Vectors and the scalar fields used for filtering live in **Zvec**, not SQLite.
- **Adapter isolation**: only `zvec_server.adapter.*` may import `zvec`. Every
  other layer works with plain types / Pydantic models.
- **Single-process constraint**: collections are process-local, so the server
  runs with a **single worker**. Run additional single-worker instances only if
  they target separate data directories.

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for the request lifecycle and
concurrency model.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
# Install all deps including the dev extra
uv sync --extra dev

# Lint, format-check, type-check
uv run ruff check
uv run ruff format --check
uv run mypy

# Run the test suite with coverage
uv run pytest --cov=zvec_server --cov-report=term

# (optional) install git pre-commit hooks
uv run pre-commit install
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full workflow and coding
standards.

## Documentation & examples

- [docs/API.md](./docs/API.md) — full REST reference with request/response examples.
- [docs/CONFIGURATION.md](./docs/CONFIGURATION.md) — every config variable.
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — internals and concurrency model.
- [examples/](./examples) — runnable Python and curl end-to-end walkthroughs.
- [benchmarks/](./benchmarks) — performance benchmarks that decompose server
  overhead (engine vs in-process vs over-HTTP) and a VectorDBBench adapter for
  zvec.org-comparable numbers.

## License

Licensed under the [Apache License 2.0](./LICENSE).

Zvec Server is an independent project and is not affiliated with or endorsed by
the upstream [Zvec](https://github.com/alibaba/zvec) project.
