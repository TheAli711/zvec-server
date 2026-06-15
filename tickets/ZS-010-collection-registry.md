---
id: ZS-010
title: In-memory collection registry loaded at startup
spec: SPEC-002
type: feature
priority: P0
status: todo
release: v0.1.0
created: 2026-06-15
---

# ZS-010: In-memory collection registry loaded at startup

## Summary

Add `CollectionManager` in `manager.py`: a process-local registry of
`ManagedCollection` entries, populated once at startup from the metadata store, so
requests resolve a collection in O(1) and never open or close handles themselves.
Also add the adapter's low-level lifecycle helpers the manager calls.

## Acceptance criteria

- [ ] `load_all()` reads every record and opens each collection with its stored
      `enable_mmap` (falling back to the server default); a missing directory or
      any open failure yields an *unavailable* entry (handle `None`) and a warning
      or error log instead of aborting startup.
- [ ] `get(name)` raises `CollectionNotFoundError` (404) or
      `CollectionUnavailableError` (503); `info(name)` works for unavailable
      entries and reports `available: false` with `stats: null`.
- [ ] `list()` returns summaries with `doc_count` read live (or `null` when
      unavailable); `counts()` returns `(loaded, unavailable)` for `/readyz`.
- [ ] `adapter/collections.py` wraps create, open, destroy, stats (`doc_count`,
      `index_completeness`), and schema serialization, turning engine failures
      into `ZvecOperationError`.
- [ ] `test_manager.py` covers reopen after restart and the missing-directory case
      against the real engine.

## Notes

- The manager must never import `zvec`; it treats handles as opaque `Any` and goes
  through `adapter.collections`.
- A registry-level `threading.Lock` guards mutations and snapshots; lookups in
  `get()` stay lock-free.
- No retry for unavailable entries in this release: restore the data and restart.
- Record options are stored as JSON; tolerate unparseable JSON by falling back to
  defaults rather than failing the load.
