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
- Releases are tag-driven and publish a Docker image to GHCR — see
  **Releasing** below. Keep `__version__` in sync with the release tag.
- Filter strings are passed through to Zvec verbatim (SQL-like: single `=`,
  single-quoted strings, `AND`/`OR`/`IN`/`BETWEEN`/`LIKE`).

## Releasing

Releases are **tag-driven**. Publishing a GitHub Release on a `v*` tag triggers
`.github/workflows/release.yml`, which runs the test suite (Python 3.12 + 3.13)
then builds and pushes a production image to `ghcr.io/theali711/zvec-server`,
tagged `vX.Y.Z`, `vX.Y`, and `latest` (the `vX.Y` / `latest` tags are applied
only for stable, non-pre-release versions). Auth is the built-in `GITHUB_TOKEN`
— never a PAT.

To cut release `vX.Y.Z`, in order:

1. Bump `__version__` in `src/zvec_server/__init__.py` to `X.Y.Z` (single source
   of truth; the tag must match it or `scripts/release.sh` aborts).
2. In `CHANGELOG.md`, move the `[Unreleased]` entries under a new
   `## [X.Y.Z] - <YYYY-MM-DD>` heading and update the link refs at the bottom
   (repoint `[Unreleased]` to compare from the new tag; add an `[X.Y.Z]` line).
3. Bump any version-pinned examples in `README.md` (the Docker pull/run snippets)
   if you want them to track the new release.
4. Run the quality gates (`uv sync --extra dev` first if tools are missing):
   `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest`.
5. Commit (`release: vX.Y.Z`) and push to `main`.
6. Run `scripts/release.sh vX.Y.Z`. It validates a clean, in-sync tree and the
   version match, pushes the tag, and creates the GitHub Release (notes pulled
   from the matching `CHANGELOG.md` section) — which triggers the publish workflow.
7. Watch it: `gh run watch $(gh run list --workflow=release.yml --limit=1 --json databaseId --jq '.[0].databaseId') --exit-status`.

Notes / gotchas:

- `scripts/release.sh` needs the GitHub CLI (`gh`), authenticated; it targets
  `main` and refuses a dirty or out-of-sync tree.
- `scripts/publish-image.sh [vX.Y.Z]` is the manual fallback: builds
  `linux/amd64` locally and pushes (run `docker login ghcr.io` first). Use it to
  back-fill a tag predating the workflow, or when CI is down.
- A `release` event runs the workflow file **from the tag's commit**, so a tag
  must point at a commit that already contains `release.yml`.
- First publish only: the GHCR package is created **private** — set it Public in
  the package settings so users can `docker pull` anonymously.
- Shell scripts must stay safe under macOS's **bash 3.2** (e.g. guard empty-array
  expansion under `set -u`).

## Keep this file current

Treat `CLAUDE.md` as living documentation. When you make a change that future
instances would need to know — a new invariant, a changed command or quality
gate, a new layer/module, a shift in the architecture, or a correction to
something stated here — update this file in the same change. Keep it concise and
non-obvious: capture what can't be quickly discovered by reading the code, and
remove guidance that becomes stale.
