---
id: ZS-026
title: Benchmark specs, datasets, and brute-force ground truth
spec: SPEC-007
type: feature
priority: P1
status: in-progress
release: v0.1.1
created: 2026-06-25
---

# ZS-026: Benchmark specs, datasets, and brute-force ground truth

## Summary

Build the data layer for SPEC-007. It needs an engine-agnostic `CollectionSpec` that
every tier can translate, dataset loaders that all return corpus, queries, and exact
neighbours in the same shape, and a brute-force ground-truth routine so recall@k is
meaningful for any dataset. This ticket also creates the `benchmarks` package and the
optional `bench` extra that the rest of the suite depends on.

## Acceptance criteria

- [ ] `benchmarks/spec.py` defines frozen `CollectionSpec` and `ScalarFieldSpec`.
      The spec covers dim, dtype, index, metric, `m`, `ef_construction`, `n_list`,
      `n_iters`, scalar fields, `vector_field`, and `enable_mmap`. `index_params()`
      returns the server-shaped `params` dict, or `None` for `flat`.
- [ ] `benchmarks/datasets.py` provides three loaders. `synthetic()` is seeded.
      `sift1m()` downloads `sift-128-euclidean.hdf5` once into
      `benchmarks/.datasets/`. `load_hdf5()` reads ann-benchmarks files
      (`train`/`test`/`neighbors`). Doc ids are row indices as strings.
- [ ] `benchmarks/groundtruth.py` computes the exact top-k for `l2`, `ip`, and
      `cosine` in query batches and caches the result as `gt-<fingerprint>.npy`.
- [ ] `pyproject.toml` gains a `bench` extra (numpy, httpx, psutil, h5py, matplotlib)
      and pytest `pythonpath = ["."]`. `benchmarks/results/` and
      `benchmarks/.datasets/` are git-ignored.
- [ ] Tests cover the ranking for each metric, batched vs unbatched results, the
      cache hit, and `index_params()` for hnsw, ivf, and flat. They
      `importorskip("numpy")`, so CI skips them when the extra isn't installed.

## Notes

- Mirror the server's vocabulary (`VECTOR_FP32`, `hnsw|flat|ivf`, `cosine|ip|l2`)
  without importing `zvec_server.models`, so that every tier can use the spec.
- For L2, rank on `||t||² − 2q·t` and drop the constant `||q||²` term. Cosine
  normalizes both sides first. Batch 256 queries per matmul to bound peak memory.
- The cache key fingerprints the shapes, a sample of rows, `k`, and the metric. It is
  cheap, but a changed dataset whose sampled rows are identical would reuse stale
  ground truth.
- Cohere is never downloaded. It comes in through `--hdf5` (ZS-029).
