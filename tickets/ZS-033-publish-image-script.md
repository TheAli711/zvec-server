---
id: ZS-033
title: scripts/publish-image.sh manual publish fallback
spec: SPEC-008
type: feature
priority: P2
status: done
release: v0.1.1
created: 2026-06-26
closed: 2026-06-29
---

# ZS-033: scripts/publish-image.sh manual publish fallback

## Summary

Add a break-glass script that builds the production image locally and pushes it to
GHCR with the same tags as the release workflow (ZS-031). It covers two cases the
workflow can't:

- **Tags created before `release.yml` existed**, such as v0.1.0. A `release` event
  runs the workflow file from the tagged commit, so re-releasing these tags would not
  publish anything.
- **Publishing while GitHub Actions is down.**

## Acceptance criteria

- [x] `scripts/publish-image.sh [vX.Y.Z]` defaults to `v<__version__>` and rejects a
      malformed tag. A tag that doesn't match `__version__` produces a warning, not
      an abort.
- [x] The script requires `docker` and `docker buildx`. It builds with
      `--platform linux/amd64 --load`, then runs `docker push` for each tag.
- [x] It always pushes `vX.Y.Z`. It pushes `vX.Y` and `latest` only for stable
      versions, matching ZS-031.
- [x] The header documents when to use the script and how to log in to GHCR. You can
      use `gh auth refresh -s write:packages` followed by
      `gh auth token | docker login ...`, or a classic PAT with `write:packages`.
- [x] After pushing, it reminds the operator to make the package public if this was
      the first push.

## Notes

- `--load` is used instead of `--push` so the script works with Docker Desktop's
  default builder. On Apple Silicon the amd64 build runs under emulation and is slow,
  but its output matches what CI produces.
- The script builds the working tree. To back-fill a tag, check that tag out first;
  the version-mismatch warning is the only guard.
- `TAG_ARGS` always contains at least the full-version tag, so it is never an empty
  array under `set -u`.

## Resolution

Added `scripts/publish-image.sh` as specified. No v0.1.0 image was back-filled in the
end: v0.1.1 is the first published image, and the README and compose examples point
at it. The script remains the manual fallback for CI outages.
