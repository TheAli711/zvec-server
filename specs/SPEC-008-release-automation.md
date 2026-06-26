---
id: SPEC-008
title: Release automation and GHCR image publishing
status: draft
created: 2026-06-26
release: v0.1.1
---

# SPEC-008: Release automation and GHCR image publishing

## Summary

Releases become tag-driven, and every release publishes a production Docker image.
Publishing a GitHub Release on a `v*` tag runs the test suite. If the tests pass, the
workflow builds the existing multi-stage `Dockerfile` (SPEC-006) and pushes it to
`ghcr.io/theali711/zvec-server` with three tags: `vX.Y.Z`, `vX.Y`, and `latest`.
Stable versions get all three; pre-releases get only `vX.Y.Z`. `scripts/release.sh`
cuts the tag and Release from a validated tree, `scripts/publish-image.sh` is a manual
fallback, and the process is documented for users and maintainers.

## Motivation

v0.1.0 ships a `Dockerfile` and `docker-compose.yml`, but every user has to clone the
repo and build the image themselves. There is nothing to `docker pull`, and nothing
ties a local build to a tested release.

Releasing is also manual and undocumented. Nothing checks that `__version__` (the
single source in `src/zvec_server/__init__.py`) matches the tag, that the tree is clean
and pushed, or that the notes match `CHANGELOG.md`. Each gap is a way to publish the
wrong thing. The next release, v0.1.1,
should be the first one users can pull, so it needs a repeatable, checked process.

## Goals

- Cut a release with one command once the version bump is committed.
- Publish only images built from a tagged commit that passed the tests on Python 3.12
  and 3.13.
- Predictable image tags: an exact version, a moving minor line, and `latest` for the
  newest stable release. Pre-releases never move `vX.Y` or `latest`.
- Use no long-lived credentials. CI authenticates with the built-in `GITHUB_TOKEN`.
- Provide a documented break-glass path for when CI is unavailable, and for tags that
  predate the workflow.

## Non-goals

- Multi-architecture images. We publish `linux/amd64` only.
- Publishing to PyPI or Docker Hub.
- Image signing, SBOMs, or provenance attestations.
- Automatic version bumps or changelog generation. `__version__` and `CHANGELOG.md` are
  still edited by hand.
- Deploying the image, or publishing images from branch pushes (no `edge` or
  `nightly` tags).
- Changing the image itself. The SPEC-006 `Dockerfile` (non-root user, `/data`
  volume, `/healthz` healthcheck, single worker) is used as-is.

## Requirements

- **R1.** A `Release` workflow must trigger on `release: published`. It must act only
  when the release tag starts with `v`.
- **R2.** The workflow must run `uv run pytest` on Python 3.12 and 3.13. It must
  publish only if both runs pass.
- **R3.** The workflow must push `ghcr.io/theali711/zvec-server:vX.Y.Z` for every
  version. It must push `vX.Y` and `latest` only for versions without a pre-release
  suffix.
- **R4.** The workflow must authenticate with `GITHUB_TOKEN`. Only the publish job
  gets `packages: write`; the workflow default is `contents: read`.
- **R5.** Two runs for the same ref must not publish concurrently. An in-flight publish
  must never be cancelled.
- **R6.** `scripts/release.sh vX.Y.Z [gh flags...]` must abort unless the tag is
  well-formed, `gh` is installed and authenticated, the tree is clean, the branch
  matches its upstream after a fetch, the tag equals `v` + `__version__`, and no
  GitHub Release exists for the tag yet.
- **R7.** `release.sh` must use the matching `## [X.Y.Z]` section of `CHANGELOG.md` as
  the release notes, falling back to GitHub-generated notes. It must mark `-suffix`
  tags as pre-releases, and it must pass extra flags through to `gh release create`.
- **R8.** `scripts/publish-image.sh [vX.Y.Z]` must build `linux/amd64` locally and push
  the same tag set the workflow would.
- **R9.** README, CONTRIBUTING, and the maintainer guide must document two things:
  pulling and running the published image, and the full release procedure.

## Design

### Flow

```
bump __version__ + move CHANGELOG entries → commit "release: vX.Y.Z" → push main
  → scripts/release.sh vX.Y.Z          validate, tag, push tag, gh release create
  → GitHub event release: published    → .github/workflows/release.yml
      test (py3.12, py3.13) ──needs──► publish (buildx → GHCR)
```

### Workflow (`.github/workflows/release.yml`)

```yaml
name: Release
on:
  release:
    types: [published]
concurrency: { group: "release-${{ github.ref }}", cancel-in-progress: false }
permissions: { contents: read }
env: { IMAGE: ghcr.io/theali711/zvec-server }
jobs:
  test:     # if: startsWith(github.event.release.tag_name, 'v')
            # 3.12/3.13 matrix: setup-uv, uv sync --extra dev, uv run pytest
  publish:  # same if; needs: test; permissions: contents read, packages write
            # setup-buildx → login-action (ghcr.io, github.actor, GITHUB_TOKEN)
            # → metadata-action → build-push-action (gha cache, provenance: false)
```

`docker/metadata-action` derives the tags:

| Rule | `v0.1.1` | `v0.1.1-rc.1` |
| --- | --- | --- |
| `type=semver,pattern=v{{version}}` | `v0.1.1` | `v0.1.1-rc.1` |
| `type=semver,pattern=v{{major}}.{{minor}}` | `v0.1` | skipped |
| `flavor: latest=auto` | `latest` | skipped |

Notes on the workflow:

- The test job repeats only the pytest part of CI (SPEC-001). Lint and type gates
  still run on every push through `ci.yml`. This job re-verifies the exact tagged
  commit before anything is pushed.
- `provenance: false` makes the push a plain single-platform manifest rather than an
  attestation manifest list. That format pulls on the widest range of runtimes.
- The image name is lowercase (`theali711`) because GHCR requires lowercase
  repository names.

### `scripts/release.sh`

```
Usage: scripts/release.sh vX.Y.Z [extra `gh release create` flags...]
  scripts/release.sh v0.1.1
  scripts/release.sh v0.1.1-rc.1        # auto-marked as a pre-release
  scripts/release.sh v0.1.1 --draft     # stage a draft instead of publishing
```

Under `set -euo pipefail`, in order:

1. Check the tag against `^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$`.
2. Require `git`, `gh`, and a passing `gh auth status`. Warn (do not abort) if the
   branch is not `main`.
3. Require a clean `git status --porcelain`, and `__version__` (read with `sed`, no
   Python needed) equal to the tag.
4. `git fetch`, then require `@` to equal `@{u}`.
5. Create the annotated tag `Release vX.Y.Z`, or reuse an existing local one. Then
   `git push origin refs/tags/vX.Y.Z`.
6. Take the notes from `CHANGELOG.md` with `awk`: everything from `## [X.Y.Z]` up to
   the next `## [`. If that is empty, use `--generate-notes` instead.
7. Add `--prerelease` for suffixed tags, unless the caller passed `--prerelease` or
   `--latest`.
8. Refuse if `gh release view` finds an existing Release. Otherwise run
   `gh release create vX.Y.Z --title vX.Y.Z`.
9. Print the `gh run watch` command and the image reference.

### `scripts/publish-image.sh`

- The tag defaults to `v<__version__>`. A mismatch with `__version__` only warns.
- Requires `docker` and `docker buildx`. It runs
  `docker buildx build --platform linux/amd64 --load`, then `docker push` for each tag.
  `--load` works with Docker Desktop's default builder, including on Apple Silicon.
- Tags match the workflow: `vX.Y.Z` always, plus `vX.Y` and `latest` for stable
  versions.
- The header documents a GHCR login that needs no PAT:
  `gh auth refresh -h github.com -s write:packages`, then
  `gh auth token | docker login ghcr.io -u TheAli711 --password-stdin`.

### Documentation

- **README**: Release and GHCR badges, plus a "Run with Docker (published image)"
  section. It covers pulling a pinned version, a table of the three tags, and
  `docker run` with `-v "$(pwd)/data:/data"`, `ZVEC_SERVER_*` env vars, and an API
  key. It ends with a `curl /healthz` check. The Compose section explains swapping
  `build:` for `image:`.
- **`docker-compose.yml`**: a comment showing that same swap.
- **CONTRIBUTING**: a "Releasing" section covering the one-command release,
  pre-releases, a manual back-fill, and making the first package public.
- **CLAUDE.md**: the maintainer guide, recording the release conventions and runbook.

## Acceptance criteria

- Publishing a Release for `vX.Y.Z` runs the tests on Python 3.12 and 3.13, then
  pushes `vX.Y.Z`, `vX.Y`, and `latest`. If a test job fails, nothing is pushed.
- A `vX.Y.Z-rc.N` tag becomes a GitHub pre-release and pushes only `vX.Y.Z-rc.N`.
- A Release whose tag does not start with `v` runs no jobs.
- Publishing needs no PAT and no repository secret other than `GITHUB_TOKEN`.
- `release.sh` aborts with a clear message on a malformed tag, missing or
  unauthenticated `gh`, a dirty tree, an out-of-sync branch, a `__version__`
  mismatch, or an existing Release.
- `docker pull ghcr.io/theali711/zvec-server:vX.Y.Z` works anonymously. The container
  passes its `/healthz` healthcheck with a mounted `/data` volume.
- `publish-image.sh` pushes the same tag set as the workflow for the same version.

## Risks and open questions

- **Tags that predate the workflow.** A `release` event runs the workflow file from
  the tagged commit. A tag created before `release.yml` existed, such as v0.1.0,
  cannot be published by re-releasing it. Open question: back-fill v0.1.0 with
  `publish-image.sh`, or make v0.1.1 the first published image.
- **Private first push.** GHCR creates a new package as private on its first push.
  Someone has to make it public once, or anonymous pulls fail.
- **Tag pushed before the Release.** `release.sh` pushes the tag before it creates the
  Release. If the Release step fails, the tag is left behind. Rerunning the script is
  safe because it reuses the existing local tag.
- **macOS bash.** Maintainers release from macOS, whose system bash is 3.2. The
  scripts must not rely on bash 4 features.
- **Back-fill builds the working tree.** `publish-image.sh` builds whatever is checked
  out. To back-fill a tag, check out that tag first. The version-mismatch warning is
  the only guard.
