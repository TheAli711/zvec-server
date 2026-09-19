---
id: ZS-051
title: Document quantization, RaBitQ, and search params
spec: SPEC-011
type: docs
priority: P1
status: done
release: v0.2.0
created: 2026-09-11
closed: 2026-09-19
---

# ZS-051: Document quantization, RaBitQ, and search params

## Summary

Make the SPEC-011 options discoverable and honest in the user docs. Each option
needs to be covered where users look for it: the API reference, the OpenAPI field
descriptions, the CHANGELOG (including the breaking strictness change), and the
README feature list. The docs must be clear about what quantization does and does
not save.

## Acceptance criteria

- [x] `docs/API.md` "Index types & metrics" lists `hnsw_rabitq`/`ivf_rabitq` with
      the Linux x86_64 restriction and has a per-index build-params table.
- [x] `docs/API.md` has a quantization section with a JSON example, stating that
      Zvec keeps the full-precision vectors and that fetch returns them unchanged.
- [x] `docs/API.md` search section has the per-index query-params table, and says
      that unknown keys return 400.
- [x] The `VectorFieldSpec.params`/`index` and `QuerySpec.params` descriptions
      match the tables.
- [x] The README key features mention the RaBitQ types, per-index build and search
      tuning, and opt-in quantization, linking to `docs/API.md`.
- [x] The CHANGELOG `[Unreleased]` has *Added* entries for each option and
      *Changed* entries for the 422 and 400 strictness.

## Notes

- Write each ticket's API.md and CHANGELOG entries in the same change as its code
  (ZS-045 through ZS-049). This ticket covers the README and a final consistency
  pass.
- Don't quote size savings as fact. Until the trade-off is measured, describe the
  quantized index as searched in place of full precision, not as a replacement for
  the stored vectors.
- `examples/` need no change: the walkthroughs use default `hnsw` collections.

## Resolution

The API reference, model descriptions, and CHANGELOG entries landed with each
feature ticket. The closing change updated the README key features to list the
RaBitQ types, per-index tuning, and opt-in quantization. In one deviation from the
plan, the quantization section was rewritten with measured results (ZS-061), so the
README now tells readers to benchmark before enabling it.
