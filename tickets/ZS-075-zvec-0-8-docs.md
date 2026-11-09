---
id: ZS-075
title: Document the Zvec 0.8.1 upgrade and measured trade-offs
spec: SPEC-015
type: docs
priority: P1
status: done
release: v0.3.0
created: 2026-11-09
closed: 2026-11-09
---

# ZS-075: Document the Zvec 0.8.1 upgrade and measured trade-offs

## Summary

Bring the README, docs/API.md, examples, model descriptions, CLAUDE.md, and the
CHANGELOG in line with SPEC-015.

## Acceptance criteria

- [x] docs/API.md: quantizer table per index, PQ settings, refiner params and
      defaults, SIFT1M numbers from ZS-074, the hnsw rotation guard, and the id
      and field-name rules.
- [x] The README and `VectorFieldSpec.index` description drop "RaBitQ: Linux
      x86_64 only".
- [x] CHANGELOG `[Unreleased]`: Added / Changed / Fixed entries, with the
      breaking items called out.

## Resolution

docs/API.md now has the per-index quantizer table, the PQ settings, the refiner
params and defaults, the SIFT1M 0.8.1 trade-off table (which replaces the 0.7.0
note), the hnsw rotation guard linked to alibaba/zvec#886, and the id and
field-name rules. The README, the model descriptions, CLAUDE.md, and the
CHANGELOG are updated too. The examples needed no change: they don't use
quantization.
