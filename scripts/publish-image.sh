#!/usr/bin/env bash
#
# publish-image.sh — build the production image locally and push it to GHCR.
#
# Normally CI does this automatically for every release (see
# .github/workflows/release.yml). Use this script for the manual cases:
#   - back-filling an image for a tag created BEFORE the release workflow existed
#     (e.g. v0.1.0, whose tag predates the workflow, so re-releasing it would not
#     run the workflow), or
#   - an ad-hoc / break-glass publish when CI is unavailable.
#
# It builds for linux/amd64 (the deployment target) via buildx, so it produces
# the same architecture as CI even when run on an Apple Silicon Mac, and applies
# the same tags the workflow would: vX.Y.Z, plus vX.Y and latest for stable
# (non-pre-release) versions.
#
# Usage:
#   scripts/publish-image.sh [vX.Y.Z]      # defaults to v<__version__>
#
# Prerequisites — log in to GHCR first (one-time; no PAT needed if you use gh):
#   gh auth refresh -h github.com -s write:packages
#   gh auth token | docker login ghcr.io -u TheAli711 --password-stdin
# or with a classic Personal Access Token that has the `write:packages` scope:
#   echo "$CR_PAT" | docker login ghcr.io -u TheAli711 --password-stdin
set -euo pipefail

IMAGE="ghcr.io/theali711/zvec-server"
PLATFORM="linux/amd64"

die() {
  echo "error: $*" >&2
  exit 1
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PKG_VERSION="$(sed -nE 's/^__version__ = "([^"]+)".*/\1/p' src/zvec_server/__init__.py)"
[[ -n "$PKG_VERSION" ]] || die "could not read __version__ from src/zvec_server/__init__.py"

TAG="${1:-v$PKG_VERSION}"
if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]]; then
  die "tag '$TAG' must look like v1.2.3 or v1.2.3-rc.1"
fi
VERSION="${TAG#v}"
[[ "$VERSION" == "$PKG_VERSION" ]] \
  || echo "warning: tag $TAG does not match __version__ $PKG_VERSION." >&2

command -v docker >/dev/null || die "docker not found"
docker buildx version >/dev/null 2>&1 || die "docker buildx not available"

# Compose the tag list. The full version is always pushed; the major/minor line
# and 'latest' are only for stable releases, matching the release workflow.
TAG_ARGS=(--tag "$IMAGE:$TAG")
if [[ "$VERSION" != *-* ]]; then
  MAJOR_MINOR="v$(echo "$VERSION" | cut -d. -f1-2)"
  TAG_ARGS+=(--tag "$IMAGE:$MAJOR_MINOR" --tag "$IMAGE:latest")
fi

echo "Building $IMAGE ($PLATFORM) with tags:"
for ((i = 1; i < ${#TAG_ARGS[@]}; i += 2)); do echo "  - ${TAG_ARGS[$i]}"; done
echo

# Build for the deployment arch and load the image into the local store. Using
# --load (not --push) keeps this working with Docker Desktop's default builder;
# we push each tag explicitly afterwards.
docker buildx build \
  --platform "$PLATFORM" \
  "${TAG_ARGS[@]}" \
  --load \
  .

echo
echo "Pushing tags to GHCR ..."
for ((i = 1; i < ${#TAG_ARGS[@]}; i += 2)); do
  docker push "${TAG_ARGS[$i]}"
done

echo
echo "Done. Pushed to $IMAGE."
echo "Pull with:  docker pull $IMAGE:$TAG"
echo "If this is the first push, set the package to Public in GitHub → Packages"
echo "so users can pull without authenticating."
