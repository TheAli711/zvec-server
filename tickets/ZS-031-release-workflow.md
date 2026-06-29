---
id: ZS-031
title: Release workflow: test, build, and push the image to GHCR
spec: SPEC-008
type: feature
priority: P0
status: done
release: v0.1.1
created: 2026-06-26
closed: 2026-06-29
---

# ZS-031: Release workflow: test, build, and push the image to GHCR

## Summary

Add `.github/workflows/release.yml` as specified in SPEC-008. When a GitHub Release is
published on a `v*` tag, the workflow runs the test suite, then builds the SPEC-006
`Dockerfile` and pushes the image to `ghcr.io/theali711/zvec-server`. It must never
publish an image built from code that fails tests, and it must not need a PAT.

## Acceptance criteria

- [x] The workflow triggers on `release: published`. Both jobs are guarded by
      `startsWith(github.event.release.tag_name, 'v')`.
- [x] The `test` job runs `uv sync --extra dev` and `uv run pytest` on Python 3.12
      and 3.13 with `fail-fast: false`. `publish` has `needs: test`.
- [x] `publish` logs in to `ghcr.io` with `GITHUB_TOKEN` and is the only job granted
      `packages: write`; the workflow default is `contents: read`. It builds with
      Buildx and the GitHub Actions cache.
- [x] Tags come from `docker/metadata-action`: `v{{version}}`,
      `v{{major}}.{{minor}}`, and `latest=auto`. A pre-release gets only its full
      version tag.
- [x] The build sets `provenance: false`, so the pushed image is a plain
      single-platform manifest.
- [x] The concurrency group is `release-${{ github.ref }}` with
      `cancel-in-progress: false`. The README shows Release and GHCR badges.

## Notes

- Lint and type checks stay in `ci.yml` (ZS-007). This workflow only reruns the tests
  against the exact tagged commit before publishing.
- The image name must be lowercase (`theali711`) because GHCR rejects uppercase
  repository names.
- Risk: a `release` event runs the workflow from the tag's commit, so tags that
  predate this file will not publish through it. ZS-033 covers that case.
- Risk: the first push creates a private package, so anonymous pulls fail until
  someone makes it public.

## Resolution

Added `.github/workflows/release.yml` as planned, using the SPEC-006 `Dockerfile`
unchanged. v0.1.1 was the first release published through it. The first push created
the GHCR package as private, and making it public is a one-time manual step, now
documented as part of ZS-034.
