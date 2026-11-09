---
id: ZS-076
title: Lift the hnsw rotation guard once Zvec fixes the regression
spec: SPEC-015
type: chore
priority: P2
status: backlog
release: v0.3.1
created: 2026-11-09
---

# ZS-076: Lift the hnsw rotation guard once Zvec fixes the regression

## Summary

ZS-069 rejects `enable_rotate` with scalar quantization on `hnsw` because of a
Zvec 0.8 regression. When an upstream release fixes it, raise the engine floor to
that release, remove the guard, and restore the hnsw int8 + rotation round-trip
test.

## Acceptance criteria

- [ ] The upstream fix is released, and the ZS-069 reproduction shows ≥ 99/100
      self-recall.
- [ ] The guard and its test are removed, the hnsw rotation round trip passes, and
      the CHANGELOG is updated.

## Notes

- Blocked on upstream: https://github.com/alibaba/zvec/issues/886.
- `tests/unit/test_upstream_regressions.py` reproduces the bug as a strict xfail.
  It starts failing (XPASS) when the engine is fixed, which is the cue for
  this ticket.
