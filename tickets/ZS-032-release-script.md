---
id: ZS-032
title: scripts/release.sh: tag and create the GitHub Release
spec: SPEC-008
type: feature
priority: P1
status: done
release: v0.1.1
created: 2026-06-26
closed: 2026-06-29
---

# ZS-032: scripts/release.sh: tag and create the GitHub Release

## Summary

Add `scripts/release.sh vX.Y.Z [gh release create flags...]` from SPEC-008. After the
version bump is committed and pushed, the script validates the repo, creates and
pushes the tag, and publishes the GitHub Release. Publishing the Release triggers the
ZS-031 workflow. The script must refuse to release from a dirty tree, an unpushed
commit, or a tag that doesn't match `__version__`.

## Acceptance criteria

- [x] The tag must match `vMAJOR.MINOR.PATCH`, optionally followed by a
      `-prerelease` suffix. Any other tag is rejected.
- [x] The script aborts if `git` or `gh` is missing, if `gh` is not authenticated, if
      the tree is dirty, if `__version__` differs from the tag, if the branch differs
      from its upstream after `git fetch`, or if a Release for the tag already
      exists. When the branch is not `main`, it prints a warning and continues.
- [x] It creates an annotated tag, or reuses one that already exists locally, and
      pushes the tag before it creates the Release.
- [x] It uses the `## [X.Y.Z]` section of `CHANGELOG.md` as the release notes. If
      that section is missing, it passes `--generate-notes` instead.
- [x] For suffixed tags it adds `--prerelease`, unless the caller already passed
      `--prerelease` or `--latest`. Extra flags such as `--draft` are forwarded to
      `gh release create`.
- [x] At the end it prints the `gh run watch` command and the image reference.

## Notes

- Use `set -euo pipefail`. Read `__version__` with `sed` so the script needs no
  Python. The only tools it depends on are `git` and `gh`.
- Maintainers run the script on macOS, so it must work under bash 3.2. Avoid bash 4
  features such as associative arrays, `mapfile`, and `${var,,}`.
- The tag is pushed before the Release is created. If the Release step fails, rerun
  the script; it reuses the tag.
- Pre-release tags publish only the `vX.Y.Z-...` image (ZS-031).

## Resolution

Added `scripts/release.sh` as specified. The branch check only warns; every other
check stops the script with an error that states which condition failed.
