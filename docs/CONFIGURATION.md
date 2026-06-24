# Configuration

Zvec Server is configured entirely through environment variables. All variables
use the `ZVEC_SERVER_` prefix and can be supplied either as real environment
variables or via a `.env` file in the working directory (see
[`.env.example`](../.env.example)). Every variable is optional; defaults are
shown below.

Configuration is loaded once at startup into a `Settings` object
(`zvec_server.config`).

## Storage

| Variable                       | Type | Default                  | Description                                                                 |
| ------------------------------ | ---- | ------------------------ | --------------------------------------------------------------------------- |
| `ZVEC_SERVER_DATA_DIR`         | path | `./data`                 | Root directory for all server data. In Docker this defaults to `/data`.     |
| `ZVEC_SERVER_METADATA_DB_PATH` | path | `<data_dir>/metadata.db` | SQLite metadata database path. Resolved relative to `DATA_DIR` if unset.    |
| `ZVEC_SERVER_COLLECTIONS_DIR`  | path | `<data_dir>/collections` | Root directory under which each collection's data lives.                    |

The metadata DB stores **only** collection metadata (name, path, schema,
timestamps). Vector data and the scalar fields used for filtering are stored by
the Zvec engine under `COLLECTIONS_DIR`, never in SQLite.

## HTTP server

| Variable            | Type | Default   | Description                                |
| ------------------- | ---- | --------- | ------------------------------------------ |
| `ZVEC_SERVER_HOST`  | str  | `0.0.0.0` | Address the server binds to.               |
| `ZVEC_SERVER_PORT`  | int  | `8000`    | Port the server binds to.                  |

> The server always runs as a **single worker** because collections are
> process-local (held in an in-memory registry). See
> [ARCHITECTURE.md](./ARCHITECTURE.md).

## Logging

| Variable                 | Type | Default | Description                                        |
| ------------------------ | ---- | ------- | -------------------------------------------------- |
| `ZVEC_SERVER_LOG_LEVEL`  | str  | `INFO`  | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`.        |
| `ZVEC_SERVER_LOG_FORMAT` | str  | `json`  | `json` for structured logs, `console` for human-readable. |

## Zvec engine

| Variable                            | Type         | Default | Description                                                       |
| ----------------------------------- | ------------ | ------- | ----------------------------------------------------------------- |
| `ZVEC_SERVER_ENABLE_MMAP`           | bool         | `true`  | Enable memory-mapped storage for collections (lower memory use).  |
| `ZVEC_SERVER_ZVEC_MEMORY_LIMIT_MB`  | int \| null  | auto    | Soft memory cap for the Zvec engine, in MB. Auto-detected if unset (e.g. from cgroup limits). |
| `ZVEC_SERVER_ZVEC_QUERY_THREADS`    | int \| null  | auto    | Number of threads Zvec uses for queries. Auto-detected from CPU if unset. |
| `ZVEC_SERVER_ZVEC_OPTIMIZE_THREADS` | int \| null  | auto    | Number of threads Zvec uses for index optimization. Auto-detected if unset. |
| `ZVEC_SERVER_ZVEC_LOG_DIR`          | path \| null | none    | Directory for the Zvec engine's own log files. Disabled if unset. |

The engine is initialized exactly once per process at startup. The
`ZVEC_SERVER_LOG_LEVEL` value is mapped to the corresponding Zvec log level (note
that `WARNING` maps to Zvec's `WARN`).

## Authentication

Authentication is **off by default** and intentionally minimal in V1: a single
static API key compared against an `Authorization: Bearer <api_key>` header. There
are no users, roles, sessions, JWTs, or auth-related database tables — the key is
supplied through the environment (or a secret manager) and is never persisted by
the server.

| Variable                    | Type        | Default | Description                                                                 |
| --------------------------- | ----------- | ------- | --------------------------------------------------------------------------- |
| `ZVEC_SERVER_AUTH_ENABLED`  | bool        | `false` | When `true`, all requests except the health probes require a valid API key. |
| `ZVEC_SERVER_API_KEY`       | str \| null | none    | The expected API key. **Required (non-empty) when auth is enabled** — startup fails otherwise. |

When enabled:

- Every request **except** `/healthz` and `/readyz` must include
  `Authorization: Bearer <api_key>`.
- Missing, malformed, or wrong credentials return `401 Unauthorized` with the
  standard error envelope (`code: "unauthorized"`) and a `WWW-Authenticate: Bearer`
  header. The interactive docs (`/docs`, `/openapi.json`) also require the key.
- The key is compared in **constant time** (`hmac.compare_digest`).

Generate a strong key, e.g.:

```bash
openssl rand -hex 32
```

The authentication layer lives in `zvec_server.auth` as a small pluggable
`AuthProvider` abstraction plus ASGI middleware, so additional schemes (multiple
keys, JWT, mTLS) can be added later without touching routing or business logic.
This single static key is **not** a substitute for TLS or a hardened gateway —
see [SECURITY.md](../SECURITY.md).

## Example `.env`

```dotenv
ZVEC_SERVER_DATA_DIR=./data
ZVEC_SERVER_HOST=0.0.0.0
ZVEC_SERVER_PORT=8000
ZVEC_SERVER_LOG_LEVEL=INFO
ZVEC_SERVER_LOG_FORMAT=console
ZVEC_SERVER_ENABLE_MMAP=true
# ZVEC_SERVER_ZVEC_MEMORY_LIMIT_MB=2048
# ZVEC_SERVER_ZVEC_QUERY_THREADS=4
# ZVEC_SERVER_ZVEC_OPTIMIZE_THREADS=2
ZVEC_SERVER_AUTH_ENABLED=false
# ZVEC_SERVER_API_KEY=change-me
```
