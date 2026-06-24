---
id: SPEC-004
title: Vector similarity search
status: implemented
created: 2026-06-16
release: v0.1.0
---

# SPEC-004: Vector similarity search

## Summary

Add `POST /collections/{name}/search`, which runs one or more nearest-neighbour queries
against a collection's vector fields and returns the best-matching documents. Each query
targets one vector field and supplies either an explicit query vector or the id of an
existing document whose stored vector becomes the query. A request caps the number of
hits (`topk`), can restrict candidates with a SQL-like scalar filter, and controls
whether vectors and which scalar fields come back in each hit. Builds on the collection
registry and locking from SPEC-002 and the document output model (`DocOut`) from
SPEC-003.

## Motivation

Similarity search is the reason to run a vector database. SPEC-002 and SPEC-003 let
clients create collections and write and fetch documents, but without a search route
the server is a key-value store with vectors attached. Clients need to run k-NN queries
over HTTP, combine them with scalar predicates (`category = 'tech' AND year > 2020`),
and ask "more like this document" without re-sending a vector the server already
stores. Without this spec there is no v0.1.0 worth shipping.

## Goals

- One endpoint covering search by explicit vector and search by stored document id.
- Several queries in one request, executed in a single engine call.
- `topk`, an optional scalar `filter`, `include_vector`, and `output_fields`, with
  `include_vector` / `output_fields` meaning exactly what they mean for fetch
  (SPEC-003).
- Optional per-query index tuning (HNSW `ef`) without leaking a Zvec type into the API.
- Searches run concurrently with other reads of the same collection and never block the
  event loop.
- A malformed filter is a client error (400), not a server error.

## Non-goals

- Text queries or server-side embedding. Queries carry client-computed vectors (or a
  stored document's vector); the server never calls a model.
- Hybrid, full-text, or keyword search. Only vector similarity plus scalar filtering.
- Reranking or custom fusion of multi-query results. The server returns whatever order
  the engine produces.
- Per-query `topk` or `filter`, or a response split into one result list per query.
- Pagination (offset or cursor) over results. `topk` is the only size control.
- Parsing, validating, or rewriting filter strings. Filters pass through verbatim.
- Normalising `score` across metrics (e.g. mapping distances into 0..1).

## Requirements

- **R1.** The server must expose `POST /collections/{name}/search`, taking a
  `SearchRequest` body and returning a `SearchResponse`.
- **R2.** `queries` must hold at least one `QuerySpec`. Each `QuerySpec` names a vector
  `field` and must set exactly one of `vector` (list of floats) or `id` (string);
  neither or both must be rejected with 422 `validation_error`.
- **R3.** `topk` must default to `10` and be bounded to 1..1000 inclusive; values
  outside the range must be rejected with 422.
- **R4.** `filter` (optional) must reach Zvec verbatim. If the engine rejects the
  request with a `ValueError`, the server must return 400 `invalid_argument`, echoing
  the filter in `details.filter` when one was sent.
- **R5.** `include_vector` (default `false`) and `output_fields` (default `null`, meaning
  all scalar fields) must shape each hit the same way they shape fetched documents.
- **R6.** Every hit must be a `DocOut` (SPEC-003) with `score` populated. Results are a
  single flat list, best first.
- **R7.** `QuerySpec.params` must accept `{"ef": <int>}` and translate it into Zvec's
  HNSW query parameter. Any other shape (absent, non-integer, boolean) must fall back to
  engine defaults instead of failing the request.
- **R8.** Search must run under the collection's shared (read) lock inside a worker
  thread: concurrent with fetches and other searches on the same collection, serialised
  only against writes.
- **R9.** An unknown collection must return 404 `collection_not_found`; a registered
  but unopened collection must return 503 `collection_unavailable`; any other engine
  failure must return 500 `zvec_operation_error`.
- **R10.** Only `zvec_server.adapter.*` may build `zvec.Query` objects or call
  `Collection.query`. The search models must not import `zvec`.
- **R11.** Search must work across restarts: a new process on the same data directory
  must return the same documents for the same query.

## Design

### Endpoint

`POST /collections/{name}/search` lives in `api/vectors.py` on the existing documents
router (prefix `/collections/{name}`, tag `documents`).

Search by vector, with a filter, HNSW tuning, and restricted output:

```json
{
  "queries": [
    { "field": "embedding", "vector": [0.12, 0.22, 0.29, 0.41], "params": { "ef": 64 } }
  ],
  "topk": 3,
  "filter": "category = 'tech' AND year > 2020",
  "include_vector": false,
  "output_fields": ["category", "year"]
}
```

Search by a stored document's vector:

```json
{ "queries": [{ "field": "embedding", "id": "a1" }], "topk": 5 }
```

Response `200`:

```json
{
  "results": [
    { "id": "a1", "score": 0.0123, "vectors": null, "fields": { "category": "tech", "year": 2021 } }
  ]
}
```

| Field            | Type                    | Default | Notes                                 |
| ---------------- | ----------------------- | ------- | ------------------------------------- |
| `queries`        | array of `QuerySpec`    | none    | At least one.                         |
| `topk`           | int, 1..1000            | `10`    | Maximum hits per query.               |
| `filter`         | string or null          | `null`  | SQL-like scalar predicate, verbatim.  |
| `include_vector` | bool                    | `false` | Include `vectors` in each hit.        |
| `output_fields`  | array of string or null | `null`  | Restrict returned scalar fields.      |

`score` is the engine's value for the field's metric, passed through unchanged.

### Models (`models/search.py`, no `zvec` import)

- `QuerySpec`: `field: str`, `vector: list[float] | None`, `id: str | None`,
  `params: dict[str, Any] | None`. An `after` validator enforces exactly one of
  `vector` / `id` ("provide exactly one of 'vector' or 'id'").
- `SearchRequest`: `queries` (`min_length=1`), `topk` (`ge=1`, `le=1000`, default 10),
  `filter`, `include_vector`, `output_fields`.
- `SearchResponse`: `results: list[DocOut]`.
- Each model carries a `json_schema_extra` example for the OpenAPI docs.

### Adapter

- `adapter/query_mapper.py`: `build_queries(specs) -> list[zvec.Query]`. A spec becomes
  `zvec.Query(field_name=..., vector=..., param=...)` or
  `zvec.Query(field_name=..., id=..., param=...)`. `param` is
  `zvec.HnswQueryParam(ef=...)` when `params["ef"]` is an `int` and not a `bool`,
  otherwise `None`.
- `adapter/operations.py`: `search(collection, req) -> SearchResponse` makes one
  `collection.query(queries=..., topk=..., filter=..., include_vector=...,
  output_fields=...)` call and maps each hit with `doc_mapper.from_zvec_doc` (SPEC-003).
  Errors follow the existing adapter pattern: a `ZvecServerError` propagates unchanged,
  `ValueError` becomes `InvalidArgumentError`, anything else `ZvecOperationError`.

### Request flow

```
api/vectors.search -> manager.get(name)            # 404 / 503 before any work
                   -> managed.read(fn)
                        run_in_threadpool: with rwlock.gen_rlock():
                            operations.search(collection, body)
```

### Errors

| Status | `code`                   | When                                                     |
| ------ | ------------------------ | -------------------------------------------------------- |
| 400    | `invalid_argument`       | Engine rejected the filter or query (e.g. `==`).         |
| 404    | `collection_not_found`   | No such collection.                                      |
| 422    | `validation_error`       | Empty `queries`, neither/both of `vector`/`id`, bad topk. |
| 500    | `zvec_operation_error`   | Any other engine failure.                                |
| 503    | `collection_unavailable` | Collection registered but not open.                      |

The API reference and README route table must document the endpoint, and the filter
syntax notes (single `=`, single-quoted strings) must point at search as well as
delete-by-filter.

## Acceptance criteria

- Searching a seeded collection by vector returns 200 and includes the nearest document.
- `filter: "category = 'tech'"` with `output_fields: ["category", "year"]` returns only
  hits whose `fields.category` is `tech`.
- Searching by the `id` of a stored document returns that document among the hits.
- A filter written with `==` returns 400 with `error.code` `invalid_argument`.
- Searching a collection that does not exist returns 404.
- A query with neither `vector` nor `id`, or with both, returns 422; so do an empty
  `queries` list and a `topk` of 0 or 1001.
- After restarting the app on the same data directory, the collection reports its
  document count and the same search still returns the document.
- No module outside `zvec_server.adapter` imports `zvec`.

## Risks and open questions

- Multi-query semantics belong to the engine. All queries go to one
  `Collection.query` call and come back as one list; how Zvec merges hits across
  queries or fields is not controlled by the server. Revisit if users need per-query
  results.
- `score` direction depends on the metric (distance vs. similarity). We pass it through;
  clients must know their collection's metric.
- Silently ignoring unrecognised `params` hides typos (`{"EF": 64}` runs with defaults).
  Accepted to keep the field open for other index types; revisit when more query
  params are supported. `flat` and `ivf` collections get engine defaults for now.
- Query by an `id` that does not exist is engine-defined. We map a `ValueError` to 400
  and anything else to 500 rather than inventing a 404.
- The 1000 `topk` cap guards against oversized responses, especially with
  `include_vector`. It may need to become configurable.
- Filter error messages are the engine's and vary in quality.

## Tickets

- ZS-018 — Query mapper: vector or document-id queries, topk, filter
- ZS-019 — Search endpoint with multi-query and output control
