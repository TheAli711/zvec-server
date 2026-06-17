---
id: ZS-018
title: Query mapper: vector or document-id queries, topk, filter
spec: SPEC-004
type: feature
priority: P0
status: todo
release: v0.1.0
created: 2026-06-17
---

# ZS-018: Query mapper: vector or document-id queries, topk, filter

## Summary

Define the search request models and the adapter code that turns them into a single
Zvec `Collection.query` call. A query targets one vector field and carries either an
explicit vector or a stored document id; the request adds `topk` and an optional
SQL-like filter. This is the engine-facing half of SPEC-004; the route is ZS-019.

## Acceptance criteria

- [ ] `QuerySpec` (`field`, `vector`, `id`, `params`) in `models/search.py` rejects
      neither or both of `vector` / `id`, and the module does not import `zvec`.
- [ ] `SearchRequest` requires at least one query and bounds `topk` to 1..1000
      (default 10); `filter` is an optional string passed through verbatim.
- [ ] `adapter/query_mapper.build_queries` builds a `zvec.Query` by vector or by id, and
      maps `params: {"ef": <int>}` to `zvec.HnswQueryParam`; other shapes (including a
      boolean `ef`) yield no param so the engine uses its defaults.
- [ ] `adapter/operations.search` issues all queries in one `collection.query` call and
      translates a `ValueError` to `InvalidArgumentError` (with `details.filter`) and
      any other failure to `ZvecOperationError`.
- [ ] Unit tests cover the exactly-one-of rule, the `queries` minimum, and the `topk`
      bounds.

## Notes

- Modules: `models/search.py`, `adapter/query_mapper.py`, `adapter/operations.py`.
  Only the adapter may import `zvec`; keep the models plain Pydantic.
- Reuse `doc_mapper.from_zvec_doc` from ZS-014 for hits rather than a second mapper.
- Risk: silently dropping unknown `params` hides typos. Acceptable while `ef` is the
  only tunable; `flat` and `ivf` get engine defaults.
- Do not validate filter syntax server-side; let Zvec reject it and map the error.
