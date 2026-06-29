# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Zvec Server is a **thin, storage-focused HTTP/REST server over the
[Zvec](https://github.com/alibaba/zvec) vector database** (FastAPI + Uvicorn,
Python 3.12+). It exposes Zvec's collection/document/search operations over JSON
so apps don't embed the Zvec library in-process. It is intentionally narrow:
**no** embedding generation (stores client-supplied vectors only), **no**
multi-tenancy/users/workspaces, and auth is limited to an optional single static
API key. Keep changes within this scope — see `CONTRIBUTING.md` before adding
features.

## Commands

Uses [uv](https://docs.astral.sh/uv/). Always run tools via `uv run`.

```bash
uv sync --extra dev          # install runtime + dev deps into .venv

# Run the server
uv run zvec-server                                                   # console entry point
uv run uvicorn zvec_server.app:create_app --factory --reload         # dev, auto-reload

# Quality gates (CI runs all of these on Python 3.12 and 3.13; all must pass)
uv run ruff check            # lint
uv run ruff format --check   # formatting
uv run mypy                  # static typing (strict-ish; see pyproject)
uv run pytest                # tests

# Auto-fix
uv run ruff check --fix
uv run ruff format

# Tests
uv run pytest --cov=zvec_server --cov-report=term      # with coverage
uv run pytest tests/unit/test_manager.py               # a single file
uv run pytest tests/integration/test_search_api.py -k search_by_id   # a single test
```

Tests run against a **real Zvec engine** in a `tmp_path`, not mocks. Integration
tests use FastAPI's `TestClient` and exercise the full app via `create_app`.

Benchmarks live in `benchmarks/` (a separate suite, optional `bench` extra:
`uv sync --extra bench`) and are run with
`uv run python -m benchmarks run --scenario smoke`. See `benchmarks/README.md`
for the three-tier overhead-decomposition design. The suite is **not** wired
into CI quality gates — its tests run only when the `bench` extra is installed
(they `pytest.importorskip("numpy")` and skip otherwise), and mypy is scoped to
`zvec_server`, so `benchmarks/` is lint-only under CI.

## Architecture

Strict layering with Zvec isolated behind an adapter. Request flow:

```
HTTP (api/, async)  →  CollectionManager (manager.py)  →  adapter/  →  Zvec engine
                                    │
                                    └→  db/metadata.py (SQLite, WAL)
```

**Invariants — these are the load-bearing design rules, enforced by convention
and tests:**

- **Adapter isolation.** Only `zvec_server.adapter.*` may `import zvec`. The
  `api`, `manager`, `models`, and `db` layers must never reference Zvec symbols —
  they work with plain types and Pydantic models. Honor the import direction in
  `docs/ARCHITECTURE.md`.
- **Two stores, strict split.** The Zvec engine (under `collections/`, one dir
  per collection) holds vectors **and** the scalar fields used for filtering/
  output. SQLite (`metadata.db`, WAL) holds **only** collection metadata
  (`CollectionRecord`: name, path, schema snapshot, timestamps). Never duplicate
  vectors or document data into SQLite.
- **In-memory registry, never per-request open/close.** `CollectionManager` opens
  each collection once at startup (`load_all()`) and keeps it in a process-local
  registry. `get(name)` is an O(1) lookup. A missing on-disk dir marks the
  collection *unavailable* (kept in registry) rather than crashing startup.
- **Concurrency.** Each `ManagedCollection` owns a fair reader/writer lock. Reads
  (fetch/search) take a shared lock, writes (insert/upsert/update/delete/flush/
  optimize) take an exclusive lock. Blocking Zvec calls run in
  `run_in_threadpool`, with the lock acquired **inside** the worker thread so the
  event loop never blocks. Different collections never block each other.
- **Single process / single worker.** Because the registry is in-process memory,
  the server runs with **one** Uvicorn worker. To scale, run separate
  single-worker instances pointed at **distinct** data directories.

### Key modules

- `app.py` — `create_app(settings=None)` factory + `lifespan` (configure logging
  → `init_zvec` (once per process, guarded) → open SQLite → `manager.load_all()`
  → set `app.state.ready`). Mounts auth middleware and exception handlers.
- `config.py` — `Settings` (pydantic-settings, env prefix `ZVEC_SERVER_`, `.env`
  support). `api_key` is a `SecretStr`; a `model_validator` requires it when
  `auth_enabled`. Data paths derive from `data_dir`.
- `errors.py` — exception hierarchy → HTTP mapping (not-found→404, exists→409,
  invalid-arg→400, validation→422). `build_error_payload(...)` is the single
  source of the JSON error envelope, reused by the auth middleware (which runs
  outside FastAPI's exception handlers).
- `auth/` — pluggable `AuthProvider` ABC (`DisabledAuthProvider` /
  `ApiKeyAuthProvider`, constant-time `hmac.compare_digest`) + a **plain ASGI**
  `AuthMiddleware` (not `BaseHTTPMiddleware`). `/healthz` and `/readyz` are public
  (`PUBLIC_PATHS`). When auth is disabled the middleware isn't even mounted. Add
  new schemes by writing a provider + wiring `build_auth_provider` — no routing
  changes.
- `adapter/` — `runtime.py` (init), `enums.py` (str⇄dtype/metric/index),
  `schema_mapper.py`, `doc_mapper.py` (REST⇄`zvec.Doc`, UUID4 on missing id,
  per-doc `Status`→result), `query_mapper.py`, `operations.py` (the only place
  that calls Zvec collection ops).

## Conventions

- `from __future__ import annotations` at the top of every module; full type
  hints on every function; Google-style docstrings on public APIs.
- The package version is **single-sourced** from `src/zvec_server/__init__.py`
  (`__version__`); pyproject uses `dynamic = ["version"]` via hatchling. Bump it
  there, not in pyproject.
- Add a `CHANGELOG.md` entry under `[Unreleased]` for any user-facing change, and
  update `README.md` / `docs/` / `examples/` when the API, config, or behavior
  changes.
- **Releases publish Docker images.** Publishing a GitHub Release on a `v*` tag
  (e.g. `v0.1.0`) triggers `.github/workflows/release.yml`, which runs the tests
  then builds and pushes a production image to `ghcr.io/theali711/zvec-server`
  (tags: full `vX.Y.Z`, `vX.Y`, and `latest` for stable). Auth is the built-in
  `GITHUB_TOKEN` — no PATs. Keep `__version__` in sync with the tag you release.
- Filter strings are passed through to Zvec verbatim (SQL-like: single `=`,
  single-quoted strings, `AND`/`OR`/`IN`/`BETWEEN`/`LIKE`).

## Keep this file current

Treat `CLAUDE.md` as living documentation. When you make a change that future
instances would need to know — a new invariant, a changed command or quality
gate, a new layer/module, a shift in the architecture, or a correction to
something stated here — update this file in the same change. Keep it concise and
non-obvious: capture what can't be quickly discovered by reading the code, and
remove guidance that becomes stale.
