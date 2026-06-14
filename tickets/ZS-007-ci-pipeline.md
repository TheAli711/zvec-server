---
id: ZS-007
title: CI pipeline: Python 3.12/3.13 test matrix and Docker build
spec: SPEC-001
type: chore
priority: P1
status: todo
release: v0.1.0
created: 2026-06-14
---

# ZS-007: CI pipeline: Python 3.12/3.13 test matrix and Docker build

## Summary

Add a GitHub Actions workflow that runs the quality gates on every push and pull
request across both supported Python versions, and checks that the container image
still builds. Nothing merges to `main` with a red gate.

## Acceptance criteria

- [ ] `.github/workflows/ci.yml` triggers on push to any branch and on
      `pull_request`, with `permissions: contents: read`.
- [ ] A `test` job with a non-fail-fast matrix over Python `3.12` and `3.13` runs
      `uv sync --extra dev`, `ruff check`, `ruff format --check`, `mypy`, and
      `pytest --cov=zvec_server` (XML + terminal reports).
- [ ] Coverage XML is uploaded as a `coverage-<python>` artifact, even on failure.
- [ ] A `docker` job builds the image with Buildx and `docker/build-push-action`
      (`push: false`, tag `zvec-server:ci`, GitHub Actions layer cache).
- [ ] A concurrency group cancels superseded runs on the same ref.

## Notes

- Use `astral-sh/setup-uv` with caching so dependency installs stay fast.
- The docker job needs the project's Dockerfile (container packaging is tracked
  separately); it only proves the image builds and never pushes.
- Tests run the real Zvec engine, so the runner needs the `zvec` wheel for Linux
  x86_64 on both Python versions.
