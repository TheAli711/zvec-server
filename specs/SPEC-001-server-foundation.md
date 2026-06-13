---
id: SPEC-001
title: Server foundation: app factory, configuration, errors, and health
status: draft
created: 2026-06-13
release: v0.1.0
---

# SPEC-001: Server foundation: app factory, configuration, errors, and health

## Summary

Stand up the skeleton every later feature plugs into: a Python 3.12+ FastAPI
application built by a factory, a `zvec-server` entry point that serves it under a
single Uvicorn worker, typed configuration from `ZVEC_SERVER_*` environment
variables, structured logging, one JSON error envelope for every failure, liveness
and readiness probes, and the tooling and CI that gate every change. Collection and
document endpoints are specified separately and mount onto this foundation.

## Motivation

Zvec is an in-process library. Applications that want it from another process or
language need a server in front of it, and that server must be boring to operate.
Several decisions here are expensive to change once endpoints exist: how the app is
constructed (tests need isolated instances with their own data directory), where
configuration comes from, what errors look like on the wire (clients will parse
them), how orchestrators probe the process, and which quality gates a change must
pass. Settling them first keeps every later endpoint consistent.

## Goals

- One factory, `create_app(settings=None)`, used by the CLI, `uvicorn --factory`,
  and the test suite.
- Configuration entirely from the environment or a `.env` file, with defaults that
  boot locally without any variables set.
- A single error envelope with stable, machine-readable `code` values.
- `/healthz` and `/readyz` suitable for container orchestrators.
- JSON logs for production, a compact console format for development.
- A reproducible `uv` workflow and CI on Python 3.12 and 3.13.

## Non-goals

- Multiple Uvicorn workers or multi-process serving. Open engine handles are
  process-local, so the server runs exactly one worker by design.
- Reloading configuration at runtime; settings are read once at startup.
- Metrics or tracing endpoints (Prometheus, OpenTelemetry).
- Authentication. The project allows at most an optional static API key, designed
  separately; this spec only keeps the error envelope usable outside FastAPI's
  exception handlers so a middleware can emit it.
- Any application concepts: users, tenants, workspaces, embedding generation.

## Requirements

- **R1.** The app must be built by `zvec_server.app.create_app(settings: Settings |
  None = None) -> FastAPI`; with no argument it uses cached environment settings.
- **R2.** Startup and shutdown must run in a FastAPI lifespan, in this order:
  configure logging, initialize the Zvec engine exactly once per process, create
  the data directories, open the metadata store, open registered collections, then
  set `app.state.ready = True`. Shutdown clears `ready`, flushes and releases
  collections, and closes the metadata store.
- **R3.** `zvec-server` (console script) and `python -m zvec_server` must run
  Uvicorn with the factory, `host`/`port` from settings, `workers=1`, and
  `log_config=None` so our logging configuration is not overridden.
- **R4.** Settings must use pydantic-settings with env prefix `ZVEC_SERVER_`,
  optional `.env` (UTF-8), case-insensitive names, and unknown variables ignored.
- **R5.** `metadata_db_path` and `collections_dir` must default to
  `<data_dir>/metadata.db` and `<data_dir>/collections` when unset, so downstream
  code always sees concrete paths.
- **R6.** `ZVEC_SERVER_LOG_FORMAT` selects `json` or `console`; Uvicorn's
  `uvicorn`, `uvicorn.error`, and `uvicorn.access` loggers must share our handler.
- **R7.** Every error response, including request validation failures, framework
  HTTP errors (unknown route, wrong method), and unhandled exceptions, must use the
  envelope `{"error": {"code", "message", "details"?}}`. Unhandled exceptions return
  a generic message; the traceback goes to the log only.
- **R8.** All server-raised errors must derive from one base class that carries an
  HTTP `status_code` and an `error_code`.
- **R9.** `GET /healthz` returns `200 {"status": "ok"}` whenever the process serves
  requests. `GET /readyz` returns `503` until startup completes, then `200` with
  loaded and unavailable collection counts, even if some collections are
  unavailable.
- **R10.** OpenAPI must be served at `/docs`, `/redoc`, and `/openapi.json`, titled
  `Zvec Server`, versioned from `zvec_server.__version__` (the single version
  source, read by hatchling).
- **R11.** CI must run `ruff check`, `ruff format --check`, `mypy`, and `pytest` on
  Python 3.12 and 3.13. Tests run against the real Zvec engine in `tmp_path`.

## Design

### Module layout

```
src/zvec_server/
  __init__.py       __version__ = "0.1.0"
  __main__.py       main(): uvicorn.run("zvec_server.app:create_app", factory=True, ...)
  app.py            create_app() + lifespan; module-level app = create_app()
  config.py         Settings, get_settings() (lru_cache)
  logging.py        configure_logging(level, fmt), get_logger(name)
  errors.py         ZvecServerError tree, ErrorResponse, build_error_payload(),
                    register_exception_handlers(app)
  deps.py           FastAPI dependencies reading singletons from app.state
  api/health.py     GET /healthz, GET /readyz
  models/common.py  HealthResponse, ReadyResponse (re-exports ErrorResponse)
```

The lifespan stores `settings`, the metadata store, and the collection manager on
`app.state`; routers reach them through `Depends(get_manager)` /
`Depends(get_metadata)`. Engine initialization lives in the adapter layer, since
only `zvec_server.adapter.*` may `import zvec`.

### Configuration

| Variable                            | Default                  |
| ----------------------------------- | ------------------------ |
| `ZVEC_SERVER_DATA_DIR`              | `./data`                 |
| `ZVEC_SERVER_METADATA_DB_PATH`      | `<data_dir>/metadata.db` |
| `ZVEC_SERVER_COLLECTIONS_DIR`       | `<data_dir>/collections` |
| `ZVEC_SERVER_HOST` / `_PORT`        | `0.0.0.0` / `8000`       |
| `ZVEC_SERVER_LOG_LEVEL`             | `INFO` (DEBUG..CRITICAL) |
| `ZVEC_SERVER_LOG_FORMAT`            | `json` (or `console`)    |
| `ZVEC_SERVER_ENABLE_MMAP`           | `true`                   |
| `ZVEC_SERVER_ZVEC_MEMORY_LIMIT_MB`  | unset (engine default)   |
| `ZVEC_SERVER_ZVEC_QUERY_THREADS`    | unset (engine default)   |
| `ZVEC_SERVER_ZVEC_OPTIMIZE_THREADS` | unset (engine default)   |
| `ZVEC_SERVER_ZVEC_LOG_DIR`          | unset (no engine logs)   |

`Settings.ensure_directories()` creates the data dir, collections dir, and the
metadata DB's parent. Invalid values (e.g. `LOG_FORMAT=xml`) fail at startup.

### Error envelope

```json
{
  "error": {
    "code": "collection_not_found",
    "message": "Collection 'articles' not found.",
    "details": { "name": "articles" }
  }
}
```

`details` is omitted when not set. Initial catalog:

| Status | `code`                      | Raised by                                |
| ------ | --------------------------- | ---------------------------------------- |
| 400    | `invalid_argument`          | `InvalidArgumentError`                   |
| 404    | `collection_not_found`      | `CollectionNotFoundError`                |
| 404    | `document_not_found`        | `DocumentNotFoundError`                  |
| 409    | `collection_already_exists` | `CollectionAlreadyExistsError`           |
| 422    | `schema_validation_error`   | `SchemaValidationError`                  |
| 422    | `validation_error`          | FastAPI `RequestValidationError`         |
| 500    | `zvec_operation_error`      | `ZvecOperationError`                     |
| 500    | `internal_error`            | base class / any unhandled exception     |
| 503    | `collection_unavailable`    | `CollectionUnavailableError`             |
| any    | `http_error`                | Starlette `HTTPException` (404, 405, ...) |

Validation errors put the Pydantic error list under `details.errors`.
`build_error_payload(code, message, details)` is the single renderer, shared by the
handlers and by any middleware that runs outside them. Errors with status >= 500
are logged with their traceback.

### Health

```
GET /healthz  ->  200 {"status": "ok"}
GET /readyz   ->  200 {"status": "ready", "collections_loaded": 2,
                       "collections_unavailable": 0}
              ->  503 {"error": {"code": "http_error", "message": "Service not ready."}}
```

Counts come from the collection registry, designed with collection management.

### Tooling

`uv` with hatchling (`dynamic = ["version"]`), a `dev` extra (pytest, pytest-cov,
httpx, ruff, mypy), ruff at line length 100, mypy with `disallow_untyped_defs`, and
pre-commit hooks for ruff and basic hygiene. GitHub Actions runs the gates per
Python version, plus a container image build without push.

## Acceptance criteria

- `uv run zvec-server` boots with no variables set and creates `./data/metadata.db`
  and `./data/collections/`.
- On an empty data dir, `GET /readyz` returns `200` with both counts at `0`;
  `GET /healthz` returns exactly `{"status": "ok"}`.
- `GET /openapi.json` returns `info.title == "Zvec Server"` and version `0.1.0`.
- A body that fails validation returns `422` with `code: validation_error` and
  `details.errors`; an unknown route returns `404` with `code: http_error`.
- An unhandled exception returns `500 internal_error` with a generic message and no
  traceback in the body.
- Several apps built by `create_app` in one process start and stop cleanly (engine
  init is guarded), which the test suite relies on.
- CI is green for lint, format, types, and tests on 3.12 and 3.13.

## Risks and open questions

- Zvec refuses a second `init` in a process. The guard makes later calls no-ops, so
  engine tuning passed to a second app in the same process is silently ignored.
  Acceptable: production runs one app per process.
- `app.py` builds a module-level `app` at import time from environment settings,
  for `uvicorn zvec_server.app:app`. The lifespan does not run on import, so this
  touches no disk, but the factory form stays the documented default.
- Readiness returns `200` while some collections are unavailable, so traffic still
  reaches a partially serving instance. Deliberate: one bad collection should not
  take down the rest. Operators should alert on `collections_unavailable > 0`.
- One worker bounds request-handling parallelism; blocking engine work must be
  offloaded to a threadpool so the event loop stays free.
