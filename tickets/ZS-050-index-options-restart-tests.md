---
id: ZS-050
title: Restart tests for quantized and SOAR ivf collections
spec: SPEC-011
type: test
priority: P2
status: done
release: v0.2.0
created: 2026-09-11
closed: 2026-09-19
---

# ZS-050: Restart tests for quantized and SOAR ivf collections

## Summary

The unit tests for ZS-045 and ZS-046 only inspect a freshly built schema. We also
need proof that Zvec persists the new index settings on disk, that the server
reopens those collections at startup, and that per-index search params (ZS-049)
still validate correctly after a reload. The index type is re-read from the reopened
engine schema, not from the request.

## Acceptance criteria

- [x] An integration test creates a quantized `hnsw` collection (`int4`,
      `enable_rotate: true`) and a SOAR `ivf` collection (`n_list: 4`,
      `use_soar: true`), seeds 300 documents in each, and optimizes both.
- [x] After restarting the app on the same data directory, both collections report
      `available: true`, identical `vectors` (including `index_param`), and
      `doc_count` 300.
- [x] The quantized collection still reports `INT4` with rotation, and the IVF one
      reports `use_soar: true`.
- [x] After the restart, search by id with `{"ef": 64}` on the hnsw field and
      `{"nprobe": 4}` on the ivf field returns `topk` hits.

## Notes

- Module: `tests/integration/test_search_api.py`. Reuse the `settings` fixture and
  two sequential `TestClient(create_app(settings))` contexts, as the existing
  persistence-reload test does.
- Use a seeded RNG and 16-dim vectors: enough documents to train IVF with a small
  `n_list`, and fast enough for CI.
- `index_param` in `GET /collections/{name}` comes from the SQLite schema snapshot,
  while search validation uses the live engine schema. The test covers both.
- RaBitQ is excluded because it is platform-dependent (ZS-048 has its own test).

## Resolution

Added a restart test that covers both collections. It checks availability, the
echoed index params, doc counts, and `ef`/`nprobe` searches after the reload. It
passed without any production code changes.
