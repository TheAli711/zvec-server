---
id: ZS-022
title: Multi-stage Dockerfile and docker-compose
spec: SPEC-006
type: feature
priority: P1
status: done
release: v0.1.0
created: 2026-06-18
closed: 2026-06-24
---

# ZS-022: Multi-stage Dockerfile and docker-compose

## Summary

Package the server as a container image and give users a one-command local deployment.
The image must build reproducibly from `uv.lock`, run as a non-root user with a single
Uvicorn worker, persist everything under `/data`, and report health through `/healthz`.
A compose file wires up the port, a host bind mount, and the common environment
variables.

## Acceptance criteria

- [x] `Dockerfile` has a uv build stage (`uv sync --no-dev --frozen`, dependencies in a
      cached layer installed with `--no-install-project` before the source is copied)
      and a `python:3.12-slim-bookworm` runtime stage that copies only `.venv` and `src`.
- [x] The runtime runs as `zvec` (uid/gid 1000), sets `ZVEC_SERVER_DATA_DIR=/data`,
      declares `VOLUME /data`, exposes 8000, and has a `HEALTHCHECK` curling `/healthz`.
- [x] `CMD` starts `uvicorn zvec_server.app:create_app --factory` with `--workers 1` and
      a comment explaining the single-worker constraint.
- [x] `docker-compose.yml` builds the image, maps `8000:8000`, mounts `./data:/data`,
      sets the main `ZVEC_SERVER_*` variables, lists engine-tuning and auth variables
      commented out, restarts `unless-stopped`, and repeats the health check.
- [x] `.dockerignore` excludes VCS data, virtualenvs, caches, `data/`, `*.db*`, `.env`
      files, tests, `.github`, and Markdown other than `README.md`.
- [x] The CI Docker build job from ZS-007 passes.

## Notes

- `README.md` must stay in the build context: the package metadata reads it during
  `uv sync`.
- Use `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, and `UV_PYTHON_DOWNLOADS=0` so the
  venv is self-contained and starts fast.
- Multiple workers would each open the same on-disk collections; the image must not
  offer a workers knob (see SPEC-002).
- Risk: a host `./data` not writable by uid 1000 breaks startup on bind mounts.
- No registry push in this ticket; the image is built locally or in CI only.

## Resolution

Added `Dockerfile`, `docker-compose.yml`, and `.dockerignore`. `curl` is installed in
the runtime stage solely for the health check. The compose file also documents the auth
variables from SPEC-005, commented out, with a note to inject the key from a secret
store.
