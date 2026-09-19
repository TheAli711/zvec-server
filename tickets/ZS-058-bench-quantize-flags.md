---
id: ZS-058
title: --quantize and --rotate benchmark flags
spec: SPEC-014
type: feature
priority: P2
status: done
release: v0.2.0
created: 2026-09-16
closed: 2026-09-19
---

# ZS-058: --quantize and --rotate benchmark flags

## Summary

Let `python -m benchmarks run` build any scenario's index quantized (SPEC-014 R1–R2):
add `quantize_type` and `enable_rotate` to `CollectionSpec`, emit them in the vector
field's `params` for the `inproc` and `http` tiers, map them to native Zvec index
params for the `engine` tier, and expose `--quantize` / `--rotate` on the CLI. This
is also the building block for the `quant` sweep (ZS-059).

## Acceptance criteria

- [x] `CollectionSpec` has `quantize_type: str | None = None` and
      `enable_rotate: bool = False`.
- [x] `index_params()` adds `quantize_type` (and `enable_rotate: true` only when
      set) for `hnsw`, `flat`, and `ivf`, alongside any existing build params.
- [x] The engine runner passes `zvec.QuantizeType` and
      `zvec.QuantizerParam(enable_rotate=...)` to `HnswIndexParam`,
      `IVFIndexParam`, and `FlatIndexParam`.
- [x] `run --quantize {fp16,int8,int4} [--rotate]` applies to every selected tier;
      without `--quantize` the index stays full FP32.
- [x] Unit tests cover the quantized `index_params()` for all three index types.
- [x] `benchmarks/README.md` lists both flags.

## Notes

- Files: `benchmarks/spec.py`, `benchmarks/runners/engine.py`, `benchmarks/cli.py`,
  `benchmarks/README.md`, `tests/benchmarks/test_spec_scenarios.py`.
- The `inproc` and `http` runners already forward `index_params()` into the create
  request, so they need no changes; the server-side validation from SPEC-011 then
  rejects anything malformed.
- Widen the `index_params()` return type from `dict[str, int]` to allow strings and
  bools.
- `--rotate` without `--quantize` has nothing to rotate; ignore it rather than error.

## Resolution

Added the two `CollectionSpec` fields, extended `index_params()` and the engine
runner's `_build_index_param`, and wired `--quantize` / `--rotate` into `run`, with a
parametrized unit test and README flag rows. The stale `CollectionSpec.enable_mmap`
comment about the Zvec 0.5.x mmap bug was updated in passing to note the 0.7.0 fix.
