---
id: ZS-078
title: Integer index and search params of 2**31 or more return 500
spec: SPEC-011
type: bug
priority: P2
status: backlog
release: v0.3.1
created: 2026-11-09
---

# ZS-078: Integer index and search params of 2**31 or more return 500

## Summary

`_int_param` and the query mapper check only that a value is a JSON integer.
Zvec's pybind constructors take fixed-width ints, so for example `ef: 2**31`
in search params, or `m: 2**31` / `n_list` / `ef_construction` in index params,
raise `TypeError`, which surfaces as `500`. Negative values are accepted and
passed to the engine unchecked.

## Reproduction

`POST /collections/{name}/search` with `"params": {"ef": 2147483648}` returns
`500`, and so does `POST /collections` with `"params": {"m": 2147483648}`.
Verified on 0.8.1.

## Acceptance criteria

- [ ] Every int param has an explicit range (at least 1..2**31-1, tighter where
      the engine documents one). Out-of-range values return `422` (index) or
      `400` (search).
- [ ] Tests cover the 2**31 and negative cases for each int param.

## Notes

- Found in review of SPEC-015. The PQ params (`num_chunk`, `num_bits`,
  `opq_*`) and `scale_factor` are already bounded.
