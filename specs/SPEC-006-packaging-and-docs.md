---
id: SPEC-006
title: Container image, documentation, and examples
status: accepted
created: 2026-06-18
release: v0.1.0
---

# SPEC-006: Container image, documentation, and examples

## Summary

Make v0.1.0 usable by someone who has never read the source. Ship a multi-stage
`Dockerfile` and a `docker-compose.yml` that run the server as a non-root, single-worker
container with persistent storage and a health check; a README plus reference docs for
the API, configuration, and architecture; runnable end-to-end examples in Python and
curl; and the contributor and community files an open-source project is expected to
have (contributing guide, security policy, code of conduct, issue and PR templates,
changelog).

## Motivation

SPEC-001 through SPEC-005 define a working server, but today the only way to run it is
from a checkout with uv, and the only API description is the generated OpenAPI page.
Users need a one-command way to start it with durable data, a clear statement of what
the server does and deliberately does not do, and copy-pasteable requests. Contributors
need to know the scope, the quality gates, and how to report bugs and vulnerabilities.
The single-worker constraint and the filter syntax (single `=`, single quotes) are easy
to get wrong; they must be written down where users will see them.

## Goals

- `docker compose up --build` gives a working server on port 8000 whose data survives
  container restarts.
- A small, reproducible image built from `uv.lock`, running as an unprivileged user,
  with exactly one Uvicorn worker and a container health check.
- A README that states scope up front ("what it is", "what it is NOT") and gets a new
  user from zero to a successful request.
- Reference docs: every endpoint with JSON examples, every `ZVEC_SERVER_*` variable,
  and the architecture and concurrency model.
- Examples that exercise the whole lifecycle and work with auth on or off.
- Contributor-facing files that encode the scope, the quality gates, and the release
  notes format.

## Non-goals

- Publishing a prebuilt image to a container registry, or any release automation. CI
  builds the image without pushing (ZS-007); users build locally.
- Multi-architecture images.
- Kubernetes manifests, Helm charts, or a TLS-terminating proxy in the compose file.
- An SDK or supported client library. The examples are illustrative scripts.
- A hosted documentation site. Docs are Markdown in the repo, plus the live `/docs` and
  `/redoc` pages.
- Any configuration for more than one worker.

## Requirements

- **R1.** The `Dockerfile` must be multi-stage: a uv-based build stage that installs
  locked, non-dev dependencies into `/app/.venv`, and a slim `python:3.12` runtime stage
  that copies only the venv and `src/`.
- **R2.** Dependency installation must be a separate, cached layer that is rebuilt only
  when `pyproject.toml` or `uv.lock` change.
- **R3.** The runtime must run as a non-root user (`zvec`, uid/gid 1000), store all state
  under a `/data` volume (`ZVEC_SERVER_DATA_DIR=/data`), expose port 8000, and define a
  `HEALTHCHECK` against `/healthz`.
- **R4.** The container command must start Uvicorn with the app factory and
  `--workers 1`, with a comment explaining why.
- **R5.** `docker-compose.yml` must build the image, publish 8000, bind-mount `./data` to
  `/data`, set the main `ZVEC_SERVER_*` variables explicitly, show the engine-tuning and
  auth variables commented out, restart `unless-stopped`, and repeat the health check.
- **R6.** `.dockerignore` must keep the build context free of VCS data, virtualenvs,
  caches, local data and database files, `.env` files, tests, and CI config.
- **R7.** `README.md` must cover: what it is and is not, key features, quickstart (uv,
  Docker Compose, smoke test), route tables, a configuration table, authentication, an
  architecture overview, development commands, and links to the docs and examples.
- **R8.** `docs/API.md`, `docs/CONFIGURATION.md`, and `docs/ARCHITECTURE.md` must be
  complete references for the v0.1.0 surface, consistent with the code.
- **R9.** `examples/python_client.py` (httpx) and `examples/curl_examples.sh` must each
  run health, create, insert, filtered search, fetch, update, delete, and drop against
  `ZVEC_SERVER_URL` (default `http://localhost:8000`), sending
  `Authorization: Bearer $ZVEC_SERVER_API_KEY` when that variable is set.
- **R10.** `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, bug and feature issue
  templates, a PR template, and `CHANGELOG.md` must exist and agree with each other on
  scope and quality gates.

## Design

### Container image (`Dockerfile`)

```
build   (uv's python3.12-bookworm-slim image)
  ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
  RUN --mount=cache,/root/.cache/uv --mount=bind pyproject.toml,uv.lock
      uv sync --no-dev --frozen --no-install-project      # deps layer
  COPY pyproject.toml uv.lock README.md ./ ; COPY src ./src
  RUN uv sync --no-dev --frozen                           # the project itself

runtime (python:3.12-slim-bookworm)
  apt: curl (for HEALTHCHECK) ; user zvec 1000:1000
  COPY --from=build --chown=zvec /app/.venv /app/src
  ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
      ZVEC_SERVER_DATA_DIR=/data
  VOLUME /data ; USER zvec ; EXPOSE 8000
  HEALTHCHECK every 30s, timeout 5s, start-period 10s, 3 retries: curl -fsS /healthz
  CMD uvicorn zvec_server.app:create_app --factory --host 0.0.0.0 --port 8000 --workers 1
```

`README.md` is copied into the build stage because the package metadata reads it, so
`.dockerignore` excludes `*.md` except `README.md`.

### Compose (`docker-compose.yml`)

A single `zvec-server` service: `build: .`, `image: zvec-server:latest`, `ports:
"8000:8000"`, `volumes: ./data:/data`. Environment sets `DATA_DIR`, `HOST`, `PORT`,
`LOG_LEVEL=INFO`, `LOG_FORMAT=json`, and `ENABLE_MMAP=true`, with
`ZVEC_MEMORY_LIMIT_MB`, `ZVEC_QUERY_THREADS`, `ZVEC_OPTIMIZE_THREADS`, `AUTH_ENABLED`,
and `API_KEY` commented out with guidance to inject the key from a secret store.

### Documentation set

| File                     | Contents                                                              |
| ------------------------ | --------------------------------------------------------------------- |
| `README.md`              | Scope, features, quickstart, route tables, config table, auth, layout |
| `docs/API.md`            | Conventions, auth, error table, filter syntax, dtypes, index types and metrics, then every endpoint with request/response JSON |
| `docs/CONFIGURATION.md`  | Every variable by section (storage, HTTP, logging, engine, auth), example `.env` |
| `docs/ARCHITECTURE.md`   | Design principles, module layout, import direction, startup/shutdown, request lifecycle, concurrency, persistence |
| `examples/README.md`     | Prerequisites and how to run each example                             |

The docs describe what SPEC-001 to SPEC-005 specify: the error envelope and code table,
the adapter-isolation rule, the one-worker constraint, SQLite holding only collection
metadata, and the auth threat model (SPEC-005). Every doc links back to the live
OpenAPI pages as the always-current reference.

### Examples

Both examples create `articles_example` (4-dim `embedding` plus a `category` field),
insert hand-written vectors (the server never embeds), search with
`category = 'tech' AND year > 2020`, fetch `a1` with its vector, update it, delete `a3`,
and drop the collection. The Python client drops the collection in a `finally` block and
surfaces the server's error body on failure. The curl script uses
`set -euo pipefail`, pretty-prints with `jq` when present, prints the body and fails on
any HTTP status of 400 or above, and keeps its optional auth-header array safe under
`set -u` on macOS's bash 3.2.

### Community files

- `CONTRIBUTING.md`: scope (no authorization, multi-tenancy, embedding generation, or
  application concepts), setup with `uv sync --extra dev`, the four quality gates,
  coding standards (typing, docstrings, layering), docs-in-the-same-PR rule, PR process,
  and bug reporting.
- `SECURITY.md`: threat model (trusted network, optional single key, no authorization or
  rate limiting, plain HTTP), supported versions (0.1.x), private reporting via GitHub
  security advisories or email, and a 3-business-day acknowledgement target.
- `CODE_OF_CONDUCT.md`: Contributor Covenant 2.1 with an enforcement contact.
- `.github/ISSUE_TEMPLATE/bug_report.md` and `feature_request.md` (the latter with a
  scope check); `.github/PULL_REQUEST_TEMPLATE.md` with a checklist mirroring the
  quality gates, docs, changelog, and scope.
- `CHANGELOG.md`: Keep a Changelog and SemVer, an `[Unreleased]` section, and the 0.1.0
  entry.

## Acceptance criteria

- `docker compose up --build` starts a container that reports healthy, answers
  `GET /healthz` with `{"status":"ok"}`, and keeps collections across
  `docker compose down` / `up`.
- The container runs as uid 1000 with one Uvicorn worker.
- Editing only `src/` does not invalidate the dependency layer.
- The CI Docker build job (ZS-007) builds the image successfully.
- Every endpoint, status code, and `ZVEC_SERVER_*` variable in the code appears in the
  docs with matching names and defaults.
- Both examples run to completion against a fresh server, with auth off and with auth on
  and `ZVEC_SERVER_API_KEY` set.
- CONTRIBUTING, the PR template, and CHANGELOG agree on the quality gates and the
  `[Unreleased]` convention.

## Risks and open questions

- Docs drift from code. Mitigated by the "docs in the same PR" rule, the PR template
  checklist, and the live OpenAPI pages; there is no automated check.
- The container writes `/data` as uid 1000. A bind-mounted `./data` owned by another
  host user will fail with permission errors; document or revisit.
- `curl` in the runtime image exists only for the health check. It adds size and attack
  surface; a Python-based probe would avoid it.
- `VOLUME /data` creates an anonymous volume when nothing is mounted, which is easy to
  lose. Compose mounts `./data` explicitly.
- The Python example needs `httpx`, which is a dev dependency, not a runtime one.
- The security and conduct contacts are a personal address until the project has a
  shared one.

## Tickets

- ZS-022 — Multi-stage Dockerfile and docker-compose
- ZS-023 — User docs: README, API, configuration, architecture
- ZS-024 — Runnable examples: Python client and curl script
- ZS-025 — Contributor and community files
