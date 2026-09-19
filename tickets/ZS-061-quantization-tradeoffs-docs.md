---
id: ZS-061
title: Report measured quantization trade-offs in the docs
spec: SPEC-014
type: docs
priority: P1
status: done
release: v0.2.0
created: 2026-09-16
closed: 2026-09-19
---

# ZS-061: Report measured quantization trade-offs in the docs

## Summary

Run the quantization sweep (ZS-059) on SIFT1M and replace the nominal claims in the
SPEC-011 docs ("roughly 2×, 4×, 8× smaller", "rotation usually recovers recall") with
what we measured (SPEC-014 R10). Users must be able to see the real disk, memory,
recall, and QPS cost of each variant before enabling quantization on a production
collection.

## Acceptance criteria

- [x] `benchmarks/README.md` has a results table for every variant (disk, server
      RSS on the `http` tier with mmap, recall@10, engine QPS) with the dataset,
      Zvec version, index params, and hardware stated.
- [x] The quantization paragraph in `docs/API.md` states that the quantized index is
      stored in addition to the full-precision vectors, summarizes the measured
      trade-offs, and points to `python -m benchmarks quant`.
- [x] `docs/API.md` no longer describes RaBitQ with unmeasured claims and says those
      index types have not been benchmarked here yet.
- [x] The CHANGELOG quantization entry tells users to benchmark first.
- [x] Docstrings no longer claim that rotation improves recall.

## Notes

- Use the `sift1m` scenario (HNSW `M=16`); report recall@10 at the top `ef` of the
  grid. Get RSS from `--tier http`, not the engine tier.
- If the numbers contradict the SPEC-011 wording, the docs change, not the defaults:
  quantization stays opt-in.
- Also touch `adapter/schema_mapper.py`'s `_quantize_kwargs` docstring, which repeats
  the rotation claim.

## Resolution

Measured on SIFT1M with Zvec 0.7.0, every quantized variant used more disk and memory
than FP32, because Zvec keeps the full-precision vectors alongside the quantized
index: `fp16` held recall (0.995) at +37% disk, `int8` lost about a point of
recall@10 at +20% disk, `int4` fell to 0.714, and rotation made `int4` worse (0.541).
Updated `benchmarks/README.md`, `docs/API.md` (including the RaBitQ note),
`CHANGELOG.md`, and the `schema_mapper.py` docstring to match. RSS was measured only
for `fp32`, `fp16`, and `int8`.
