---
id: SPEC-012
title: Group-by search
status: implemented
created: 2026-09-12
release: v0.2.0
---

# SPEC-012: Group-by search

## Summary

Add `POST /collections/{name}/search/group-by`: run **one** nearest-neighbour query,
bucket the hits by the value of a scalar field, and return the best `topk_per_group`
hits from each of the best `group_count` groups. The canonical use is retrieval over
chunked documents: chunks carry a `doc_id` field, and the client wants the top two
chunks from each of the top five documents rather than ten chunks that may all come
from one long document. The endpoint is a thin pass-through to Zvec's native group-by
query and reuses the `QuerySpec`, filter, and output controls of `/search`.

## Motivation

`POST /collections/{name}/search` (SPEC-004) returns a flat top-k list. When many
vectors share a parent (chunks of a document, images of a product, messages of a
thread), a flat top-k is routinely dominated by one parent. Clients work around it by
over-fetching (`topk` in the hundreds) and grouping on their side. That wastes
bandwidth — every hit crosses the wire as JSON, vectors included if requested — and
still does not guarantee `group_count` distinct groups.

Zvec answers this in the engine with `Collection.group_by_query`, which the server can
call now that it runs on Zvec 0.7.0 (SPEC-010). Without an endpoint, users who need
result diversity must embed Zvec in-process — exactly what this server exists to
avoid — or accept the over-fetch.

## Goals

- Expose Zvec's group-by query over REST with the same query, filter, and output
  semantics as `/search`.
- Keep the request familiar: a `QuerySpec` (vector or document id, plus the per-index
  search `params` introduced by SPEC-011), `filter`, `include_vector`,
  `output_fields`.
- Return an easy-to-consume response: ordered groups, each with its value and its
  hits in the existing `DocOut` shape.
- Report bad input as `400` consistently, including on empty collections where the
  engine itself performs no check.

## Non-goals

- Multi-query or fused group-by. One query per request; `/search` stays the
  multi-query endpoint.
- Aggregations. This is not SQL `GROUP BY`: no counts, sums, or per-group statistics
  beyond the hits themselves.
- Grouping by several fields, by an expression, or by a vector field.
- Paging through groups (offsets or continuation tokens). Clients raise
  `group_count` instead.
- Preserving the group value's native type in the response (values are strings; R4).
- Server-side reranking or deduplication. The server stays a storage layer.

## Requirements

- **R1.** The server must expose `POST /collections/{name}/search/group-by` taking a
  `GroupSearchRequest` body: `query` (`QuerySpec`, required), `group_by` (string,
  required), `group_count` (int, 1–1000, default `10`), `topk_per_group` (int,
  1–1000, default `3`), `filter` (string or null, default `null`), `include_vector`
  (bool, default `false`), `output_fields` (list of string or null, default `null`
  meaning all scalar fields).
- **R2.** `query` must accept exactly what a `/search` query accepts: exactly one of
  `vector` or `id`, and optional `params` validated against the field's index type
  as defined by SPEC-011 (unknown or mistyped keys return `400`).
- **R3.** A successful call must return `200` with a `GroupSearchResponse`:
  `{"groups": [{"value": ..., "results": [DocOut, ...]}, ...]}`. Groups are ordered
  by their best hit and hits within a group best first. At most `group_count` groups
  and `topk_per_group` hits per group are returned; fewer when the data has fewer.
- **R4.** A group's `value` must always be a string: non-string values are rendered
  with `str()` (an `INT64` field's `3` becomes `"3"`), and a null value becomes `""`.
- **R5.** A `group_by` naming anything other than one of the collection's scalar
  fields must return `400 invalid_argument` with details
  `{"group_by": <name>, "valid": [<sorted scalar field names>]}` — on an empty
  collection too. The server must check this itself because Zvec only rejects an
  unknown group field when there is data to search.
- **R6.** A malformed filter or any other argument Zvec rejects with `ValueError` must
  return `400 invalid_argument`; any other engine failure returns
  `500 zvec_operation_error`. A missing collection returns `404`, an unavailable one
  `503`, and a body that fails schema validation `422 validation_error`.
- **R7.** `include_vector` and `output_fields` must apply to every hit exactly as in
  `/search`. Grouping must still work when `output_fields` omits the `group_by`
  field.
- **R8.** The operation is a read: it takes the collection's shared lock inside a
  threadpool worker, so it runs concurrently with other reads and with `optimize`
  (SPEC-010), and never blocks the event loop.
- **R9.** Only `zvec_server.adapter.*` may touch Zvec. Models live in
  `models/search.py`, the engine call in `adapter/operations.py`, the route in
  `api/vectors.py`.
- **R10.** The route sits behind the auth middleware like every non-health route; no
  change to `PUBLIC_PATHS`.
- **R11.** The endpoint must be documented in `docs/API.md`, the README route table,
  `CHANGELOG.md`, and both runnable examples.

## Design

### Endpoint

```
POST /collections/{name}/search/group-by
```

```json
{
  "query": { "field": "embedding", "vector": [0.12, 0.22, 0.29, 0.41] },
  "group_by": "doc_id",
  "group_count": 5,
  "topk_per_group": 2,
  "filter": "lang = 'en'",
  "output_fields": ["doc_id", "title"]
}
```

Response `200`:

```json
{
  "groups": [
    { "value": "doc-7",
      "results": [{ "id": "doc-7#3", "score": 0.011, "fields": { "doc_id": "doc-7" } }] },
    { "value": "doc-2",
      "results": [{ "id": "doc-2#0", "score": 0.019, "fields": { "doc_id": "doc-2" } }] }
  ]
}
```

A separate route (rather than a mode flag on `/search`) keeps both response models
simple: `/search` stays a flat `results` list and this route always returns `groups`.

### Errors

| Condition                                               | Status | `error.code`            |
| ------------------------------------------------------- | ------ | ----------------------- |
| Collection not registered                               | 404    | `collection_not_found`  |
| Collection registered but unavailable                   | 503    | `collection_unavailable`|
| Body invalid (no `group_by`, `group_count: 0`, `vector` and `id`) | 422 | `validation_error` |
| Unknown `group_by`, bad filter, bad search `params`     | 400    | `invalid_argument`      |
| Any other engine failure                                | 500    | `zvec_operation_error`  |

### Layers

- **models** (`models/search.py`): `GroupSearchRequest` (fields and bounds per R1,
  with an OpenAPI example), `GroupOut {value: str, results: list[DocOut]}`, and
  `GroupSearchResponse {groups: list[GroupOut]}`. No Zvec imports.
- **adapter** (`adapter/operations.py`): `group_search(collection, req)`.
  1. Collect `{f.name for f in collection.schema.fields}` (scalar fields only) and
     raise `InvalidArgumentError` with the sorted list if `group_by` is not in it.
  2. Build the native query with the existing `query_mapper.build_queries()`, passing
     `query_mapper.vector_index_types(collection)`, so per-index `params`
     validation is shared with `/search`.
  3. Call `collection.group_by_query(query, req.group_by, group_count=...,
     topk_per_group=..., filter=..., include_vector=..., output_fields=...)`.
  4. Map `ValueError` to `InvalidArgumentError`, re-raise `ZvecServerError`, wrap
     anything else in `ZvecOperationError`.
  5. Map each returned group to `GroupOut(value=str(group.group_by_value),
     results=[doc_mapper.from_zvec_doc(d, include_vector=...) for d in group.docs])`.
- **api** (`api/vectors.py`): an async handler that resolves the collection with
  `manager.get(name)` and runs `operations.group_search` via `managed.read(...)`.
- **manager**: no changes; the existing shared-lock read path is sufficient.

## Acceptance criteria

- A group-by over a seeded collection returns one group per distinct value, each hit
  carries the group's value, and the expected best hit leads its group.
- A `filter` narrows the candidate set before grouping (groups with no matching
  documents disappear).
- `group_by: "nope"` returns `400` on both a seeded and an empty collection, and the
  empty-collection response lists the valid scalar fields.
- A malformed filter and an index-inappropriate search param (e.g. `nprobe` on an
  `hnsw` field) return `400`.
- A missing collection returns `404`.
- `include_vector: true` with `output_fields` excluding the group field returns the
  stored vectors and only the requested fields for every hit.
- `ruff`, `ruff format --check`, `mypy`, and `pytest` pass; docs and CHANGELOG are
  updated.

## Risks and open questions

- **Result size.** The bounds allow up to 1000 × 1000 hits in one response. We keep
  the same per-dimension cap as `topk` and rely on clients asking for what they need;
  a combined cap can be added later if it proves to be a problem.
- **Stringified values.** Rendering values as strings loses the type (`3` vs `"3"`),
  and a null value (`""`) is indistinguishable from an empty-string value. Accepted
  for a uniform JSON shape; clients that care can request the field in
  `output_fields` and read the typed value from the hits.
- **Engine semantics.** How deep Zvec searches to fill `group_count` groups is
  engine-defined; a dominant group can still yield fewer groups than requested. We
  pass the parameters through and do not try to compensate.
- **Validation gap.** Zvec validates `group_by` and the filter only when there is
  data to search. The server pre-validates `group_by` against the schema, but a
  malformed filter on an empty collection may return no groups instead of `400`; we
  accept that rather than parse filters ourselves (they pass through verbatim).

## Tickets

- ZS-052 — Group-by search endpoint
- ZS-053 — Group-by honors include_vector and output_fields
- ZS-054 — Document group-by search
