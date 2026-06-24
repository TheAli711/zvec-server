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

## Pull request process

1. Create a feature branch off the default branch.
2. Make your change with tests and docs.
3. Ensure all quality gates pass locally.
4. Add an entry under the `Unreleased` section of
   [`CHANGELOG.md`](./CHANGELOG.md).
5. Open a PR using the [PR template](./.github/PULL_REQUEST_TEMPLATE.md); link any
   related issues and describe what changed and why.
6. Address review feedback. Keep the PR focused; prefer several small PRs over one
   large one.

## Reporting bugs

Open a [bug report](./.github/ISSUE_TEMPLATE/bug_report.md) with steps to
reproduce, the exact request/response where possible, and your environment.

For security issues, **do not** open a public issue — see
[SECURITY.md](./SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](./LICENSE).
