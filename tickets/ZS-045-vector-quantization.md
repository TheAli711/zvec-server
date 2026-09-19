---
id: ZS-045
title: Vector quantization for hnsw, flat, and ivf indexes
spec: SPEC-011
type: feature
priority: P1
status: done
release: v0.2.0
created: 2026-09-11
closed: 2026-09-19
---

# ZS-045: Vector quantization for hnsw, flat, and ivf indexes

## Summary

Let a vector field opt into Zvec 0.7.0 scalar quantization at create time.
`vectors[].params.quantize_type` takes `fp16`, `int8`, or `int4`, and
`params.enable_rotate` (bool) applies a random rotation before quantizing. Both
apply to `hnsw`, `flat`, and `ivf`. The settings are fixed for the collection's
lifetime and are echoed back in `index_param`.

## Acceptance criteria

- [x] `enums.QUANTIZE_TYPES` and `parse_quantize_type()` resolve `fp16`/`int8`/
      `int4` case-insensitively to `zvec.QuantizeType`. Anything else, including
      `rabitq` and non-strings, raises `SchemaValidationError` (422) with
      `details.valid`.
- [x] `enable_rotate` must be a JSON boolean and requires `quantize_type`, and maps
      to `zvec.QuantizerParam(enable_rotate=...)`.
- [x] For every index × quantize combination, the built schema reports
      `quantize_type` and `quantizer_param.enable_rotate`.
- [x] An `int8` + rotation collection created over HTTP echoes
      `"quantize_type": "INT8"`, and still returns the right nearest neighbour after
      optimize.
- [x] `docs/API.md`, the `VectorFieldSpec.params` description, and the CHANGELOG
      describe the options.

## Notes

- Modules: `adapter/enums.py`, `adapter/schema_mapper.py` (a shared
  `_quantize_kwargs()` and a `_bool_param()` validator), and
  `models/collections.py` (description only; `params` stays free-form).
- Zvec keeps the full-precision vectors next to the quantized index, and fetch
  returns originals. Don't promise the full 2×/4×/8× disk saving in the docs.
- `rabitq` is deliberately not a `quantize_type`. It gets its own index types in
  ZS-048.
- Unknown-key rejection is ZS-047. This ticket validates only the keys it adds.

## Resolution

Added `QUANTIZE_TYPES`/`parse_quantize_type` to the adapter enums and a shared
quantization kwarg builder to the schema mapper, used by the `hnsw`, `ivf`, and
`flat` builders. Unit tests cover the full index × type matrix and the rejection
cases. Integration tests cover an `int8` + rotation round trip and a 422 for
`int2`.
