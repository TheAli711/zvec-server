# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Vector quantization: `hnsw`, `flat`, and `ivf` indexes accept
  `params.quantize_type` (`fp16` / `int8` / `int4`) and `params.enable_rotate`.
  Benchmark first: on SIFT1M it cost disk, memory, and recall without a speed
  gain (see `docs/API.md`).
- `hnsw_rabitq` and `ivf_rabitq` index types (RaBitQ quantization; Linux
  x86_64 servers only — other platforms return `422`).
- Streaming export: `GET /collections/{name}/export` streams a consistent
  snapshot of every document as NDJSON (re-importable via `/docs/insert`),
  without blocking writes.
- Group-by search: `POST /collections/{name}/search/group-by` returns the best
  hits per value of a scalar field (e.g. top chunks per document).
- Search `params` for every index type: `ef`, `radius`, `is_linear`,
  `is_using_refiner` (hnsw / hnsw_rabitq), `nprobe` (ivf), plus `scale_factor`
  (ivf_rabitq). Previously only HNSW `ef` was honored.
- `ivf` indexes accept `params.use_soar` (SOAR spilling for better recall).

### Changed

- Unknown or mistyped search `params` now return `400` instead of being silently
  ignored (e.g. `ef` on a `flat` or `ivf` field).
- Unknown keys in a vector field's `params` are now rejected with `422` instead
  of being silently ignored, so a typo can't quietly build a different index.
- Requires **Zvec 0.7.0** (was 0.5.0). Picks up upstream fixes for crash
  recovery, filter validation, query validation (`topk`, field names), and
  mmap storage. Thread-pool CPU pinning is now off by default in Zvec, which
  suits containers.
- `POST /collections/{name}/optimize` no longer blocks reads: searches and
  fetches on the collection continue while it runs (writes still wait).
  Concurrent optimize calls on the same collection are serialized.
- Shutdown now explicitly closes every collection, releasing Zvec's on-disk
  lock immediately so a replacement instance in a rolling restart can open the
  collections without waiting.

### Fixed

- A background recovery that reopened a collection just as it was dropped
  could re-attach (and leak) the handle; it is now discarded and closed.
- Dropping a collection now waits for in-flight requests on it, and requests
  queued behind the drop (or behind shutdown) fail with `503`/`404` instead of
  running against the destroyed handle.

- Collection names are validated against Zvec's 3-64 character limit. Names
  outside it previously passed validation, then failed in the engine and were
  misreported as `409 collection_already_exists`; they now return `422`. Other
  engine schema rejections also return `422` instead of `409`.

- With `ZVEC_SERVER_ENABLE_MMAP=true` (the default), a few freshly-optimized
  documents could come back from search with empty ids
  (`Failed to find target chunk`). Fixed by the Zvec 0.7.0 upgrade.

## [0.1.2] - 2026-07-08

### Added

- Collections that fail to open at startup (e.g. a rolling-restart race where
  the previous process instance still held Zvec's on-disk lock) now self-heal:
  a background task retries the open with exponential backoff
  (`ZVEC_SERVER_COLLECTION_RECOVERY_INITIAL_DELAY_SECONDS` /
  `..._MAX_DELAY_SECONDS`, defaults `30.0` / `300.0`) until it succeeds, instead
  of requiring a full server restart to recover.

### Fixed

- `scripts/release.sh` no longer aborts with an "unbound variable" error on bash
  3.2 (the version shipped with macOS) when run without extra flags.

## [0.1.1] - 2026-06-29

### Added

- **Automated Docker image publishing to GHCR.** A `Release` GitHub Actions
  workflow runs the test suite and, on every published release tagged `v*`,
  builds and pushes a production image to `ghcr.io/theali711/zvec-server`. Images
  are tagged with the full version (`vX.Y.Z`), the major/minor line (`vX.Y`), and
  `latest` for the most recent stable release. Authentication uses the built-in
  `GITHUB_TOKEN` (no long-lived personal access tokens). The README documents
  pulling a specific version and running the published image with a mounted data
  volume and `ZVEC_SERVER_*` environment variables.
- **Benchmarking suite** under `benchmarks/` (optional `bench` extra:
  `uv sync --extra bench`). Decomposes server overhead across three tiers that
  run the same workload through progressively more of the stack — `engine`
  (native Zvec SDK, the floor), `inproc` (Pydantic + `ManagedCollection` lock +
  adapter, no socket), and `http` (real uvicorn subprocess over loopback) — so
  the server-logic tax (`inproc − engine`) and transport tax (`http − inproc`)
  are measured separately. Reports recall@k against brute-force ground truth,
  latency percentiles, QPS, RSS, and HTTP payload sizes, emitting JSON plus a
  markdown report and plots. Tiered scenarios (`smoke` → `sift1m` →
  `cohere1m`/`cohere10m`) and a VectorDBBench REST adapter
  (`benchmarks/vdbbench/`, manual install) for zvec.org-comparable numbers.
  Additive only — no changes to the runtime server. Not wired into CI gates
  (lint-only; tests require the `bench` extra).

## [0.1.0] - 2026-06-24

Initial release: a lightweight, storage-focused HTTP server that exposes the
[Zvec](https://github.com/alibaba/zvec) vector database over REST.

### Added

- **FastAPI HTTP server** with an app factory (`zvec_server.app:create_app`), a
  `zvec-server` console entry point, and OpenAPI docs at `/docs` and `/redoc`.
- **Health endpoints**: `GET /healthz` (liveness) and `GET /readyz` (readiness
  with loaded/unavailable collection counts).
- **Collection management**: create (`POST /collections`), list
  (`GET /collections`), inspect (`GET /collections/{name}`), drop
  (`DELETE /collections/{name}`), plus `flush` and `optimize` operations.
- **Document operations** under `/collections/{name}`: `docs/insert`,
  `docs/upsert`, `docs/update`, `docs/delete` (by ids or by SQL-like filter),
  `docs/fetch`, and `GET docs/{doc_id}`.
- **Vector similarity search** (`POST /collections/{name}/search`) supporting
  multiple queries (by vector or by existing document id), `topk`, SQL-like
  scalar filters, and optional vector/field output.
- Support for multiple **vector dtypes** (`VECTOR_FP32/FP16/FP64/INT8`, sparse
  variants) and **scalar dtypes**, **index types** (`hnsw`/`flat`/`ivf`), and
  **metrics** (`cosine`/`ip`/`l2`).
- **In-memory collection registry** (`CollectionManager`) with per-collection
  reader/writer locks and threadpool offload of blocking engine calls.
- **SQLite metadata store** (WAL mode) holding only collection metadata; vectors
  and filterable fields live in the Zvec engine.
- **Adapter isolation**: only `zvec_server.adapter.*` imports `zvec`.
- **Configuration** via `ZVEC_SERVER_*` environment variables / `.env`, including
  data directories, host/port, logging, and Zvec engine tuning.
- **Optional API-key authentication** (`Authorization: Bearer`), off by default,
  via a pluggable `AuthProvider` + ASGI middleware in `zvec_server.auth`.
- **Structured logging** (JSON or console).
- **Consistent error envelope** with appropriate HTTP status codes.
- **Containerization**: multi-stage `Dockerfile` (non-root, single worker,
  healthcheck) and `docker-compose.yml`.
- **Documentation** (`README.md`, `docs/API.md`, `docs/CONFIGURATION.md`,
  `docs/ARCHITECTURE.md`) and runnable **examples** (Python `httpx` client and a
  `curl` script).
- **Tooling**: uv-based workflow, ruff (lint + format), mypy, pytest with
  coverage, pre-commit hooks, and a GitHub Actions CI pipeline (test matrix over
  Python 3.12/3.13 plus a Docker build).

[Unreleased]: https://github.com/TheAli711/zvec-server/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/TheAli711/zvec-server/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/TheAli711/zvec-server/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/TheAli711/zvec-server/releases/tag/v0.1.0
