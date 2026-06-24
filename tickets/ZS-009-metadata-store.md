---
id: ZS-009
title: SQLite metadata store for collection records
spec: SPEC-002
type: feature
priority: P0
status: done
release: v0.1.0
created: 2026-06-15
closed: 2026-06-24
---

# ZS-009: SQLite metadata store for collection records

## Summary

Add `db/metadata.py`: a `CollectionRecord` dataclass and a thread-safe
`MetadataStore` over stdlib `sqlite3` that persists only collection metadata. It is
the authoritative list of which collections exist; vectors and document data stay
in Zvec and must never be written here.

## Acceptance criteria

- [x] `connect()` opens one connection with `check_same_thread=False`, enables WAL
      and foreign keys, creates the `collections` table, and sets
      `PRAGMA user_version` to `SCHEMA_VERSION` (1). Calling it twice is a no-op.
- [x] Columns: `name` (PK), `path`, `schema_version`, `embedding_dimension`,
      `embedding_model`, `primary_vector`, `metric`, `index_type`, `options_json`,
      `schema_json`, `created_at`, `updated_at`.
- [x] `add` raises `CollectionAlreadyExistsError` on a PK conflict; `get` returns
      `None` for unknown names; `list` is ordered by name; `delete` and `touch` on
      unknown names are no-ops.
- [x] Every call holds an internal `threading.Lock`; use after `close()` raises
      `RuntimeError`; `close()` is idempotent.
- [x] `now_iso()` returns a timezone-aware UTC ISO 8601 string.
- [x] `test_metadata.py` covers round-trips, nullable columns, reopen persistence,
      and a multi-threaded add/get/list smoke test.

## Notes

- Column order is derived once from the dataclass fields so the INSERT, SELECT,
  and row mapping cannot drift apart.
- Migrations: bump `SCHEMA_VERSION` and add one step per version in `_migrate`,
  keyed off `user_version`. Version 1 is the baseline table.
- `db` depends only on the stdlib and `errors`; it must not import the manager or
  adapter.

## Resolution

Added `db/metadata.py` with `CollectionRecord`, `MetadataStore`, `now_iso`, and
`SCHEMA_VERSION`, plus unit tests. The lifespan opens the store after creating the
data directories and closes it last on shutdown.
