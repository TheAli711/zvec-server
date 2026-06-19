---
id: ZS-003
title: Settings from ZVEC_SERVER_* environment variables and .env
spec: SPEC-001
type: feature
priority: P0
status: in-progress
release: v0.1.0
created: 2026-06-14
---

# ZS-003: Settings from ZVEC_SERVER_* environment variables and .env

## Summary

Introduce `zvec_server.config.Settings`, a pydantic-settings model that resolves all
server configuration from `ZVEC_SERVER_*` variables or a `.env` file, with defaults
that boot locally. Derived storage paths must always be concrete so the rest of the
code never handles `None` paths.

## Acceptance criteria

- [ ] Env prefix `ZVEC_SERVER_`, `.env` (UTF-8) support, case-insensitive names,
      unknown variables ignored.
- [ ] Fields and defaults: `data_dir=./data`, `metadata_db_path`,
      `collections_dir`, `host=0.0.0.0`, `port=8000`, `log_level=INFO`
      (`DEBUG|INFO|WARNING|ERROR|CRITICAL`), `log_format=json` (`json|console`),
      `enable_mmap=true`, `zvec_memory_limit_mb`, `zvec_query_threads`,
      `zvec_optimize_threads`, `zvec_log_dir` (all unset by default).
- [ ] An after-validator fills `metadata_db_path = data_dir/metadata.db` and
      `collections_dir = data_dir/collections` only when they are unset.
- [ ] `ensure_directories()` creates the data dir, collections dir, and the
      metadata DB's parent directory.
- [ ] `get_settings()` returns a cached instance; `create_app(settings)` accepts an
      explicit override for tests.

## Notes

- Invalid literals (e.g. `ZVEC_SERVER_LOG_FORMAT=xml`) should fail fast at startup
  with a Pydantic validation error rather than falling back silently.
- Engine tuning values pass straight to the Zvec init call; `None` means "let the
  engine decide".
- The model should be easy to extend with cross-field validators; an optional API
  key is in project scope and will need one.
- Provide `.env.example` listing every variable with its default.
