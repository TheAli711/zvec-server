---
id: ZS-061
title: Report measured quantization trade-offs in the docs
spec: SPEC-014
type: docs
priority: P1
status: todo
release: v0.2.0
created: 2026-09-16
---

# ZS-061: Report measured quantization trade-offs in the docs

## Summary

Run the quantization sweep (ZS-059) on SIFT1M and replace the nominal claims in the
SPEC-011 docs ("roughly 2×, 4×, 8× smaller", "rotation usually recovers recall") with
what we measured (SPEC-014 R10). Users must be able to see the real disk, memory,
recall, and QPS cost of each variant before enabling quantization on a production
collection.

## Acceptance criteria

- [ ] `benchmarks/README.md` has a results table for every variant (disk, server
      RSS on the `http` tier with mmap, recall@10, engine QPS) with the dataset,
      Zvec version, index params, and hardware stated.
- [ ] The quantization paragraph in `docs/API.md` states that the quantized index is
      stored in addition to the full-precision vectors, summarizes the measured
      trade-offs, and points to `python -m benchmarks quant`.
- [ ] `docs/API.md` no longer describes RaBitQ with unmeasured claims and says those
      index types have not been benchmarked here yet.
- [ ] The CHANGELOG quantization entry tells users to benchmark first.
- [ ] Docstrings no longer claim that rotation improves recall.

## Notes

- Use the `sift1m` scenario (HNSW `M=16`); report recall@10 at the top `ef` of the
  grid. Get RSS from `--tier http`, not the engine tier.
- If the numbers contradict the SPEC-011 wording, the docs change, not the defaults:
  quantization stays opt-in.
- Also touch `adapter/schema_mapper.py`'s `_quantize_kwargs` docstring, which repeats
  the rotation claim.
