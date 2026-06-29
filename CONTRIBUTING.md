# Contributing to Zvec Server

Thanks for your interest in contributing! This project aims to be a small,
high-quality, **thin storage layer over Zvec**. Contributions that keep it that
way — focused, well-tested, well-typed — are very welcome.

By participating you agree to abide by our
[Code of Conduct](./CODE_OF_CONDUCT.md).

## Scope

Before proposing a feature, please confirm it fits the project's scope. Zvec
Server deliberately does **not** include:

- authorization, or multi-tenancy,
- embedding generation (the server stores client-supplied vectors only),
- application concepts (users, workspaces, knowledge bases, etc.).

If you're unsure whether something is in scope, open a
[feature request](./.github/ISSUE_TEMPLATE/feature_request.md) to discuss it
before writing code.

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
# clone your fork, then:
uv sync --extra dev          # install runtime + dev dependencies into .venv

# (optional) install the git pre-commit hooks
uv run pre-commit install
```

Run the server locally:

```bash
uv run zvec-server
# or
uv run uvicorn zvec_server.app:create_app --factory --reload
```

## Quality gates

All of these must pass before a PR is merged (CI runs them on Python 3.12 and
3.13):

```bash
uv run ruff check            # lint
uv run ruff format --check   # formatting
uv run mypy                  # static type checking
uv run pytest                # tests
uv run python scripts/tracker.py --check   # TRACKER.md matches specs/ + tickets/
```

To auto-fix lint and formatting locally:

```bash
uv run ruff check --fix
uv run ruff format
```

Run tests with coverage:

```bash
uv run pytest --cov=zvec_server --cov-report=term
```

## Coding standards

- **Python 3.12+** with full type hints on every function.
- `from __future__ import annotations` at the top of each module.
- **Google-style docstrings** on public functions and classes.
- Keep functions small and readable.
- Respect the layering rules: only `zvec_server.adapter.*` may `import zvec`; the
  `api` and `manager` layers must not. See
  [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).
- Don't change a published model field name, endpoint path, or public signature
  without good reason and corresponding updates to tests and docs.
- Add or update tests for any behavior change. New endpoints/behaviors need both
  happy-path and error-path tests.

## Documentation

If your change affects the API, configuration, or behavior, update the relevant
docs in the same PR:

- [`README.md`](./README.md)
- [`docs/`](./docs)
- [`examples/`](./examples)

## Spec-driven workflow

Work in this repository flows **spec → tickets → tracker**, all versioned next to
the code (details in [`specs/README.md`](./specs/README.md)):

1. **Spec** — a new capability starts as `specs/SPEC-NNN-*.md`, written before any
   code: problem, goals and non-goals, requirements, proposed API, acceptance
   criteria. It is reviewed as a `draft` and becomes `accepted` once agreed.
2. **Tickets** — an accepted spec is broken into `tickets/ZS-NNN-*.md`, each one a
   reviewable unit of work with its own acceptance criteria. Bugs get a ticket too,
   filed against the spec they affect.
3. **Tracker** — [`TRACKER.md`](./TRACKER.md) is generated from the front matter of
   every spec and ticket by `python scripts/tracker.py`; CI fails if it is stale.

Trivial changes (typos, dependency bumps) don't need a ticket; anything that
changes behavior does, and a new capability needs an accepted spec first.

## Pull request process

1. Make sure the change has a ticket (and, for a new capability, an accepted
   spec) — see [Spec-driven workflow](#spec-driven-workflow).
2. Create a feature branch off the default branch.
3. Make your change with tests and docs. In the same change, flip the ticket to
   `done` and regenerate the tracker with `python scripts/tracker.py`.
4. Ensure all quality gates pass locally.
5. Add an entry under the `Unreleased` section of
   [`CHANGELOG.md`](./CHANGELOG.md).
6. Open a PR using the [PR template](./.github/PULL_REQUEST_TEMPLATE.md); reference
   the ticket (`Closes: ZS-NNN`) and describe what changed and why.
7. Address review feedback. Keep the PR focused; prefer several small PRs over one
   large one.

## Releasing

Releases are tag-driven. Publishing a GitHub Release for a version tag (`v*`)
triggers [`.github/workflows/release.yml`](./.github/workflows/release.yml),
which runs the test suite and pushes a production image to
`ghcr.io/theali711/zvec-server` (tagged `vX.Y.Z`, `vX.Y`, and `latest` for stable
releases) using the built-in `GITHUB_TOKEN` — no personal access tokens.

To cut a release (requires the [GitHub CLI](https://cli.github.com), `gh`):

```bash
# 1. Bump the single-sourced version and commit it.
#    Edit src/zvec_server/__init__.py: __version__ = "0.1.1"
#    Move the CHANGELOG [Unreleased] entries under a new [0.1.1] heading.
git commit -am "release: v0.1.1"
git push origin main

# 2. Tag + create the GitHub Release (this triggers the publish workflow).
scripts/release.sh v0.1.1
```

`scripts/release.sh` validates that the tag matches `__version__`, requires a
clean tree in sync with `origin`, pushes the tag, and creates the Release using
the matching `CHANGELOG.md` section as the notes. Pre-release tags
(`vX.Y.Z-rc.1`) are marked as GitHub pre-releases and only get the `vX.Y.Z` image
tag (no `vX.Y` / `latest`).

**Backfilling an image manually** (e.g. `v0.1.0`, whose tag predates the
workflow, so re-releasing it would not run the workflow) or a break-glass publish
when CI is down:

```bash
# Log in to GHCR once (no PAT needed if you use gh):
gh auth refresh -h github.com -s write:packages
gh auth token | docker login ghcr.io -u TheAli711 --password-stdin

scripts/publish-image.sh v0.1.0   # builds linux/amd64 and pushes all tags
```

On the **first** publish, the GHCR package is private — set it to Public under
GitHub → your profile → Packages → `zvec-server` → Package settings so users can
`docker pull` without authenticating.

## Reporting bugs

Open a [bug report](./.github/ISSUE_TEMPLATE/bug_report.md) with steps to
reproduce, the exact request/response where possible, and your environment.

For security issues, **do not** open a public issue — see
[SECURITY.md](./SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](./LICENSE).
