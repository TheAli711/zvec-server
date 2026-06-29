---
id: ZS-034
title: Document the release process
spec: SPEC-008
type: docs
priority: P1
status: done
release: v0.1.1
created: 2026-06-26
closed: 2026-06-29
---

# ZS-034: Document the release process

## Summary

Document the SPEC-008 process for two audiences. Users need to know that images
exist, which tag to pull, and how to run a published image with persistent data and
`ZVEC_SERVER_*` configuration. Maintainers need the exact steps to cut a release:
bump the version, update the changelog, pass the gates, run the script, and watch the
workflow. They also need to know about the manual fallback.

## Acceptance criteria

- [x] The README has a "Run with Docker (published image)" section. It covers pulling
      a pinned version, the tag table (`vX.Y.Z`, `vX.Y`, `latest`), and `docker run`
      with `-v "$(pwd)/data:/data"`, env vars, and an API key, plus a `/healthz`
      check. The Compose section explains how to switch to `image:`.
- [x] `docker-compose.yml` has a comment explaining how to use the published image
      instead of building locally.
- [x] CONTRIBUTING has a "Releasing" section. It covers the bump and changelog, the
      commit, `scripts/release.sh`, pre-release behaviour, a manual back-fill with
      `publish-image.sh`, and making the first package public.
- [x] CLAUDE.md has a step-by-step "Releasing" runbook: bump `__version__`, move the
      CHANGELOG entries and link refs, update the README pins, run the quality gates,
      commit `release: vX.Y.Z`, run `release.sh`, then `gh run watch`.
- [x] CHANGELOG has an `Added` entry for GHCR publishing under `[Unreleased]`.

## Notes

- CLAUDE.md is the living guide for maintainers and coding agents. Keep the runbook
  there, next to the invariants.
- Pin the examples to a real published tag, not `latest`, so copy-pasted deployments
  are reproducible.
- After the first real release, record the gotchas it exposes.

## Resolution

The README, CONTRIBUTING, compose, and CHANGELOG changes shipped with the workflow and
scripts. The CLAUDE.md runbook followed after v0.1.1 was cut, and it records what that
release taught: `gh` must be installed and authenticated, a `release` event runs the
workflow from the tag's commit, a new GHCR package starts private, and scripts must
stay bash 3.2 safe. The pinned examples point at v0.1.1, the first published image.
