---
id: ZS-041
title: Require Zvec 0.7.0
spec: SPEC-010
type: chore
priority: P0
status: done
release: v0.2.0
created: 2026-09-09
closed: 2026-09-19
---

# ZS-041: Require Zvec 0.7.0

## Summary

Raise the engine floor from `zvec>=0.5.0` to `zvec>=0.7.0` and re-lock. Every other
SPEC-010 ticket depends on 0.7.0, and so does the mmap empty-id fix (ZS-040). This
ticket changes only the dependency, so any API break in the engine shows up here,
separate from behaviour changes.

## Acceptance criteria

- [x] `pyproject.toml` declares `zvec>=0.7.0`, and `uv.lock` resolves `zvec` 0.7.0.
- [x] `ruff check`, `ruff format --check`, `mypy`, and `pytest` pass on Python 3.12
      and 3.13 with no adapter changes, or any needed changes stay inside
      `zvec_server.adapter`.
- [x] With `--mmap`, a benchmark run returns no empty ids, and recall matches
      `--no-mmap` (ZS-040).
- [x] The mmap caveat in `benchmarks/README.md` is updated to match.

## Notes

- Upstream 0.7.0 also fixes crash recovery, filter validation, and query validation
  (`topk`, field names), and turns thread-pool CPU pinning off by default. Check
  that the error-mapping tests (400 for bad filters, 422 for bad schemas) still see
  the same exception types.
- On-disk compatibility: open a data directory written under 0.5.0 before merging
  (SPEC-010 risk).
- Benchmarks default to `--no-mmap`. Keep that default and change only the caveat
  text.
- `uv sync --extra dev` after pulling. The Docker image picks up the new lock.

## Resolution

Bumped the requirement to `zvec>=0.7.0` in `pyproject.toml` and re-locked `uv.lock`
from 0.5.0 to 0.7.0. The suite passed with no adapter or mapper changes. The
benchmark README mmap note now says the 0.5.x forward-store bug is fixed in 0.7.0,
the minimum this server requires, and that `--mmap` runs are clean.
