---
id: ZS-035
title: release.sh aborts with an unbound variable error on bash 3.2
spec: SPEC-008
type: bug
priority: P1
status: done
release: v0.1.2
created: 2026-06-29
closed: 2026-06-29
---

# ZS-035: release.sh aborts with an unbound variable error on bash 3.2

## Summary

On macOS's default bash 3.2, `scripts/release.sh` fails with "unbound variable" when
run without extra `gh` flags. It fails after the tag is pushed and before the GitHub
Release is created, so the publish workflow (ZS-031) never runs and no image is
pushed. The cause is that bash 3.2, under `set -u`, treats expanding an empty array
as a reference to an unset variable. Bash 4.4 and later do not, which is why Linux
and CI never hit it.

## Reproduction

Environment: macOS, with the stock `/bin/bash` 3.2.57 first on `PATH` (the script uses
`#!/usr/bin/env bash`), `gh` authenticated, and a clean tree in sync with `origin`.

1. Run `scripts/release.sh v0.1.1` with no extra flags, so `EXTRA_ARGS=()`.
2. Validation passes, the tag is pushed, and the CHANGELOG notes are picked up.
3. `gh release create "$TAG" --title "$TAG" "${NOTES_ARGS[@]}" "${EXTRA_ARGS[@]}"`
   aborts with `EXTRA_ARGS[@]: unbound variable`.

Minimal repro: `/bin/bash -c 'set -u; a=(); echo "${a[@]}"'` prints
`a[@]: unbound variable`. A pre-release tag fails earlier, at the `${EXTRA_ARGS[*]}`
check that decides whether to add `--prerelease`.

**Observed:** the script exits 1 with the tag pushed, but no Release and no image.

**Expected:** the Release is created and the workflow publishes the image.

## Acceptance criteria

- [x] On bash 3.2, `scripts/release.sh vX.Y.Z` with no extra flags reaches
      `gh release create`.
- [x] Pre-release detection works when `EXTRA_ARGS` is empty.
- [x] Extra flags such as `--draft` are still forwarded unchanged and correctly
      quoted.
- [x] Comments in the script explain the idiom, and CHANGELOG has a `Fixed` entry.

## Notes

- `${arr[@]+"${arr[@]}"}` expands to nothing for an empty array and to the quoted
  elements otherwise. Inside `[[ ... ]]`, `${arr[*]:-}` is enough.
- `publish-image.sh` is not affected, because its `TAG_ARGS` is never empty.
- To recover, rerun the script after the fix. It reuses the tag that was already
  pushed.

## Resolution

Guarded both `EXTRA_ARGS` expansions in `scripts/release.sh` and added a CHANGELOG
`Fixed` entry. The fix shipped in v0.1.2. "Scripts must stay bash 3.2 safe" was added
to the maintainer release gotchas in CLAUDE.md (ZS-034).
