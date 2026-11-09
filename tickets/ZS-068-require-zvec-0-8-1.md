---
id: ZS-068
title: Require Zvec 0.8.1
spec: SPEC-015
type: chore
priority: P0
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-068: Require Zvec 0.8.1

## Summary

Raise the engine floor from `zvec>=0.7.0` to `zvec>=0.8.1` and re-lock. This ticket
covers only the dependency and the test fallout. The new options are separate
tickets, so any engine break shows up here on its own.

## Acceptance criteria

- [x] `pyproject.toml` declares `zvec>=0.8.1`, and `uv.lock` resolves 0.8.1.
- [x] Tests that compared `quantizer_param` to `{"enable_rotate": ...}` accept the
      six keys Zvec now reports (`enable_rotate`, `num_chunk`, `num_bits`,
      `fast_scan`, `opq_iter`, `opq_pq_iter`).
- [x] The RaBitQ tests no longer expect `422` off Linux x86_64. RaBitQ now builds
      on macOS ARM64 too.
- [x] Collections created by 0.7.0 open, search, accept writes, and re-optimize
      under 0.8.1. Checked manually; see the Resolution.
- [x] All quality gates pass.

## Notes

- 0.8.0's breaking change (the Jieba dictionary API was removed) doesn't affect
  us. The server never calls `init(jieba_dict_dir=...)`.
- The 0.8.1 "pending WAL recovery before read-only open" note doesn't apply. The
  server always opens collections writable.

## Resolution

Bumped to `zvec>=0.8.1` and re-locked. The test fallout was the six-key
`quantizer_param` echo and RaBitQ now building on macOS ARM64.
`RABITQ_SUPPORTED` now reflects 0.8.1's platforms, and the 422 branch is kept
for the rest. Before the bump, collections were built with 0.7.0 (plain, int8,
and int8 + rotation × hnsw/ivf/flat). Under 0.8.1 all nine opened, kept 50/50
self-recall@1, accepted writes, and kept full recall after a re-optimize.
