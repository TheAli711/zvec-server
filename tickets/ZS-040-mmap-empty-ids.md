---
id: ZS-040
title: Search returns empty ids after optimize with mmap enabled
spec: SPEC-004
type: bug
priority: P1
status: done
release: v0.2.0
created: 2026-06-28
closed: 2026-09-19
---

# ZS-040: Search returns empty ids after optimize with mmap enabled

## Summary

With memory-mapped storage enabled, which is the server default
(`ZVEC_SERVER_ENABLE_MMAP=true`), a few freshly-optimized documents come back from
search with an empty `id`. The hit keeps a score but can't be traced to a document,
so clients can't fetch it, and recall drops. The fault is in Zvec's mmap forward
store, not in the server. We found it while benchmarking.

## Reproduction

1. Run the server with its defaults (mmap on), or use the benchmark suite with
   `--mmap`, e.g. `uv run python -m benchmarks run --scenario smoke --mmap`.
2. Create an `hnsw` collection, insert a few thousand documents, call
   `POST /collections/{name}/optimize`, then run searches.

Observed: a few hits come back with `"id": ""` and a normal score, and the engine
logs `mmap_forward_store.cc ... Failed to find target chunk` on stderr. Benchmark
recall is lower with `--mmap` than with `--no-mmap`.

Expected: every hit has the id of a stored document, and mmap on and off give the
same results.

## Acceptance criteria

- [x] Searches after optimize with mmap enabled return no hits with empty ids.
- [x] `--mmap` benchmark runs match `--no-mmap` recall on the same scenario.
- [x] The minimum `zvec` requirement includes the upstream fix, and CI passes on
      it.
- [x] The benchmark README's mmap caveat and the CHANGELOG reflect the fix.

## Notes

- Upstream Zvec bug in the mmap forward store (0.5.x). Nothing in `adapter/` can
  fix it safely. Dropping empty-id hits would hide lost results, and turning mmap
  off by default would change memory behaviour for every deployment.
- Blocked on upstream: keep in the backlog until a Zvec release ships the fix, then
  raise the pin in `pyproject.toml`.
- Meanwhile, benchmarks default to `--no-mmap` and the harness skips empty ids so
  recall numbers stay usable (see `benchmarks/README.md`, SPEC-007).
- Operators who hit this can set `ZVEC_SERVER_ENABLE_MMAP=false` or pass
  `options.enable_mmap: false` per collection.

## Resolution

Fixed upstream in Zvec 0.7.0. The ticket was scheduled under SPEC-010 and closed by
raising the requirement to `zvec>=0.7.0` together with ZS-041. No server code
changed. The benchmark README now says `--mmap` runs are clean and match
`--no-mmap` recall, and the CHANGELOG lists the fix under *Fixed*.
