---
id: ZS-049
title: Search params for every index type
spec: SPEC-011
type: feature
priority: P1
status: done
release: v0.2.0
created: 2026-09-11
closed: 2026-09-19
---

# ZS-049: Search params for every index type

## Summary

The query mapper turns `queries[].params` into a Zvec query param only for HNSW
`{"ef": int}`. Everything else is silently dropped: IVF `nprobe`, exact search, a
distance radius, and all RaBitQ options. Build the right query-param object from the
field's actual index type, and reject params that do not apply to it with a `400`.

## Acceptance criteria

- [x] `hnsw`/`hnsw_rabitq` accept `ef` (int), `radius` (float), `is_linear` (bool),
      and `is_using_refiner` (bool). `ivf` accepts `nprobe` (int). `ivf_rabitq`
      accepts `nprobe`, `radius`, `is_linear`, `is_using_refiner`, and
      `scale_factor` (float). `flat` accepts none.
- [x] The index type is read from the open collection's schema
      (`vector_index_types`) inside the search call.
- [x] Unknown keys, wrong JSON types (`"ef": "64"`, `"is_linear": 1`), and params
      on a field that does not exist return `400 invalid_argument` with
      `field`/`unknown`/`valid` details.
- [x] Integration tests return correct results for hnsw (`ef`, `is_linear`,
      `is_using_refiner`, `radius`), ivf (`nprobe`), and flat (no params).
- [x] The `http` and `inproc` benchmark runners send only the knob that applies
      (`ef` for hnsw, `nprobe` for ivf), and the benchmark docs drop the "engine
      tier only" IVF caveat.
- [x] `docs/API.md` has a per-index query-params table. The CHANGELOG lists the
      new params and the 400 behaviour change.

## Notes

- Modules: `adapter/query_mapper.py` (per-index `(class, {param: type})` table),
  `adapter/operations.py` (pass index types to `build_queries`), and
  `models/search.py` (description only).
- Type checks: `bool` must be a real boolean. `int` must be an integer and not a
  bool. `float` accepts any JSON number, so `"radius": 10` is valid.
- Breaking: clients that send `ef` to a flat or ivf field start getting 400. Flag
  this in the CHANGELOG.
- The benchmark runners (SPEC-007) currently always send `ef`. They would break
  against IVF collections once validation is strict.

## Resolution

Rewrote the query mapper around a table of Zvec query-param classes and allowed
params per index type, keyed by the live schema's index type name, with strict type
checks. `operations.search` now passes the field-to-index map. A shared
`server_query_params()` helper keeps the benchmark `inproc` and `http` runners in
line with the engine tier.
