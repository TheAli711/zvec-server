---
id: ZS-001
title: Set up project tooling: uv, ruff, mypy, pytest, pre-commit
spec: SPEC-001
type: chore
priority: P0
status: in-progress
release: v0.1.0
created: 2026-06-14
---

# ZS-001: Set up project tooling: uv, ruff, mypy, pytest, pre-commit

## Summary

Create the `zvec-server` package skeleton and the developer toolchain so every later
ticket lands against the same gates: a `uv`-managed project with a `src/` layout,
ruff for lint and format, mypy for static typing, pytest with coverage, and
pre-commit hooks. The package version must be single-sourced so releases cannot
drift.

## Acceptance criteria

- [ ] `pyproject.toml` builds with hatchling from `src/zvec_server`, requires
      Python >= 3.12, reads the version dynamically from
      `src/zvec_server/__init__.py`, and ships `py.typed`.
- [ ] Runtime deps pinned by floor (`fastapi`, `uvicorn[standard]`, `pydantic`,
      `pydantic-settings`, `zvec>=0.5.0`, `readerwriterlock`,
      `python-json-logger`); a `dev` extra adds pytest, pytest-cov, httpx, ruff,
      mypy. `uv.lock` is committed.
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, and
      `uv run pytest` all pass on an empty-but-importable package.
- [ ] mypy disallows untyped and incomplete defs, warns on `Any` returns, and
      ignores missing stubs only for `zvec`, `readerwriterlock`, `pythonjsonlogger`.
- [ ] `.pre-commit-config.yaml` runs the standard hygiene hooks plus ruff (with
      `--fix`) and ruff-format.

## Notes

- Ruff: line length 100, target py312, rules `E F I UP B C4 SIM RUF`; ignore `B008`
  because FastAPI puts `Depends(...)`/`Query(...)` in argument defaults. Tests may
  use `assert False` (`B011`).
- pytest: `testpaths = ["tests"]`, `-ra -q`; coverage with branch tracking over
  `zvec_server`, excluding `if TYPE_CHECKING:` blocks.
- Tests must hit the real Zvec engine in `tmp_path`; do not introduce engine mocks
  here. Keep the ruff pre-commit rev roughly in step with the ruff floor.
- Every module starts with `from __future__ import annotations`.
