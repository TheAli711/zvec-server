#!/usr/bin/env bash
#
# release.sh — cut a new release of zvec-server.
#
# Creates (if needed) and pushes a version tag, then publishes a GitHub Release
# for it. Publishing the release triggers .github/workflows/release.yml, which
# runs the test suite and pushes a production image to
# ghcr.io/theali711/zvec-server (tags: vX.Y.Z, vX.Y, and latest for stable).
#
# Usage:
#   scripts/release.sh vX.Y.Z [extra `gh release create` flags...]
#
# Examples:
#   scripts/release.sh v0.1.1
#   scripts/release.sh v0.2.0-rc.1            # auto-marked as a pre-release
#   scripts/release.sh v0.1.1 --draft         # stage a draft (won't publish yet)
#
# Requirements: git, gh (GitHub CLI, authenticated via `gh auth login`).
#
# Notes:
#   - The tag must match __version__ in src/zvec_server/__init__.py (the single
#     source of truth). Bump and commit that first.
#   - For the v0.1.0 image (whose tag predates this workflow), use
#     scripts/publish-image.sh instead — see that script's header.
set -euo pipefail

die() {
  echo "error: $*" >&2
  exit 1
}

TAG="${1:-}"
[[ -n "$TAG" ]] || die "usage: $0 vX.Y.Z [extra gh release create flags...]"
shift
EXTRA_ARGS=("$@")

# --- validate tag shape (vMAJOR.MINOR.PATCH with optional -prerelease) ---------
if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]]; then
  die "tag '$TAG' must look like v1.2.3 or v1.2.3-rc.1"
fi
VERSION="${TAG#v}"
IS_PRERELEASE=0
[[ "$VERSION" == *-* ]] && IS_PRERELEASE=1

# --- prerequisites ------------------------------------------------------------
command -v git >/dev/null || die "git not found"
command -v gh >/dev/null || die "gh (GitHub CLI) not found — install it: brew install gh"
gh auth status >/dev/null 2>&1 || die "not authenticated with gh — run: gh auth login"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- repo state ---------------------------------------------------------------
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" == "main" ]] || echo "warning: on branch '$BRANCH', not 'main'." >&2
[[ -z "$(git status --porcelain)" ]] || die "working tree is dirty — commit or stash first."

# Version in code must match the tag (single-sourced in __init__.py).
PKG_VERSION="$(sed -nE 's/^__version__ = "([^"]+)".*/\1/p' src/zvec_server/__init__.py)"
[[ -n "$PKG_VERSION" ]] || die "could not read __version__ from src/zvec_server/__init__.py"
if [[ "$PKG_VERSION" != "$VERSION" ]]; then
  die "tag $TAG implies version $VERSION, but __version__ is $PKG_VERSION.
       Bump src/zvec_server/__init__.py (and commit) first."
fi

# Local branch must be in sync with its upstream so the tag points at pushed code.
git fetch --quiet origin
if UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
  [[ "$(git rev-parse @)" == "$(git rev-parse '@{u}')" ]] \
    || die "local branch differs from $UPSTREAM — push/pull so the release points at pushed code."
fi

# --- create & push the tag ----------------------------------------------------
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "tag $TAG already exists locally; reusing it."
else
  echo "creating annotated tag $TAG ..."
  git tag -a "$TAG" -m "Release $TAG"
fi
echo "pushing tag $TAG to origin ..."
git push origin "refs/tags/$TAG"

# --- release notes from CHANGELOG (the section for this version), if present ---
NOTES="$(awk -v ver="$VERSION" '
  $0 ~ ("^## \\[" ver "\\]") { capture = 1; next }
  capture && /^## \[/        { exit }
  capture                    { print }
' CHANGELOG.md)"

NOTES_ARGS=()
if [[ -n "${NOTES//[$' \t\n']/}" ]]; then
  echo "using CHANGELOG.md section for release notes."
  NOTES_ARGS=(--notes "$NOTES")
else
  echo "no CHANGELOG.md section for $VERSION — letting GitHub generate notes."
  NOTES_ARGS=(--generate-notes)
fi

# Auto-mark pre-release tags (vX.Y.Z-...) as GitHub pre-releases unless the
# caller already passed a (pre)release flag. ${arr[*]:-} keeps this safe for an
# empty array under `set -u` on bash 3.2 (macOS default).
if [[ "$IS_PRERELEASE" -eq 1 && ! " ${EXTRA_ARGS[*]:-} " =~ " --prerelease " && ! " ${EXTRA_ARGS[*]:-} " =~ " --latest " ]]; then
  EXTRA_ARGS+=(--prerelease)
fi

# --- create the GitHub Release (this triggers the publish workflow) -----------
if gh release view "$TAG" >/dev/null 2>&1; then
  die "a GitHub Release for $TAG already exists — delete it first or pick a new tag."
fi

echo "creating GitHub Release $TAG ..."
# ${arr[@]+"${arr[@]}"} avoids an 'unbound variable' error for an empty array
# under `set -u` on bash 3.2 (the version shipped with macOS).
gh release create "$TAG" --title "$TAG" "${NOTES_ARGS[@]}" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}

echo
echo "Done. Release $TAG published."
echo "Watch the publish workflow:  gh run watch \$(gh run list --workflow=release.yml --limit=1 --json databaseId --jq '.[0].databaseId')"
echo "Resulting image once green:  ghcr.io/theali711/zvec-server:$TAG"
