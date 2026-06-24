---
id: SPEC-003
title: Document operations
status: implemented
created: 2026-06-15
release: v0.1.0
---

# SPEC-003: Document operations

## Summary

Add the document API under `/collections/{name}/docs`: insert, upsert, update,
delete (by ids or by a SQL-like filter), batch fetch by ids, and a single-document
GET. A document is a string id plus named vectors and named scalar fields; the
server passes client-supplied vectors to Zvec unchanged and reports the engine's
outcome per document. Builds on SPEC-002 (registry, per-collection locks,
adapter) and SPEC-001 (error envelope).

## Motivation

Collections are useless until clients can put data in and read it back. Zvec's
Python API works on `zvec.Doc` objects and returns a `Status` per document for
batch writes; clients over HTTP need a JSON shape for documents, a way to learn
which documents in a batch failed, generated ids when they have none of their own,
and the same filter language Zvec uses. Similarity search reuses the document
output shape and is specified separately.

## Goals

- JSON document model shared by all write endpoints and returned by reads.
- Batch writes with per-document results in input order, not all-or-nothing.
- Server-generated ids when the client omits one.
- Delete by an explicit id list or by a filter, never both.
- Fetch many ids in one call, plus a REST-style single-document GET.
- Writes exclusive, reads shared, per collection (SPEC-002 locking).

## Non-goals

- Generating embeddings or accepting raw text to embed.
- Server-side validation of vector dimensions or field types against the schema;
  Zvec is the source of truth and its rejections are passed back.
- Multi-collection or transactional batches; partial success is reported instead.
- Listing, paging, or scanning all documents in a collection.
- Returning the number of documents removed by a filter delete.
- Rewriting or sanitizing filter strings; they reach Zvec verbatim.

## Requirements

- **R1.** `POST /collections/{name}/docs/insert`, `/docs/upsert`, and
  `/docs/update` must accept `{"docs": [DocIn, ...]}` with at least one document.
- **R2.** A `DocIn` without `id` must get `uuid4().hex` (32 hex chars), and the
  generated id must appear in the response.
- **R3.** Write responses must list one result per input document, in input order,
  with `id`, `ok`, the engine status `code` name, and `message`, plus
  `success_count` and `error_count`. A batch with per-document failures still
  returns `200`.
- **R4.** `POST /docs/delete` must take exactly one of `ids` or `filter`; neither
  or both → `422 validation_error`.
- **R5.** Id deletes return per-id results and `ok` = all succeeded; filter deletes
  return `ok: true`, the echoed `filter`, and a message.
- **R6.** `POST /docs/fetch` takes `ids` (min 1), optional `output_fields`, and
  `include_vector` (default `false`), and returns found documents keyed by id;
  missing ids are omitted, not errors.
- **R7.** `GET /docs/{doc_id}` accepts `include_vector` and repeated
  `output_fields` query params and returns one document or `404
  document_not_found`.
- **R8.** Engine `ValueError`s (malformed filter, bad document) → `400
  invalid_argument`; other engine failures → `500 zvec_operation_error`; unknown
  collection → `404`; unavailable collection → `503`.
- **R9.** Writes and deletes run under the collection's exclusive lock; fetches
  under the shared lock; all engine calls run in the threadpool.

## Design

### Endpoints

```
POST /collections/{name}/docs/insert   WriteRequest  -> 200 WriteResponse
POST /collections/{name}/docs/upsert   WriteRequest  -> 200 WriteResponse
POST /collections/{name}/docs/update   WriteRequest  -> 200 WriteResponse
POST /collections/{name}/docs/delete   DeleteRequest -> 200 DeleteResponse
POST /collections/{name}/docs/fetch    FetchRequest  -> 200 FetchResponse
GET  /collections/{name}/docs/{doc_id}               -> 200 DocOut | 404
```

Routes live in `api/vectors.py` (tag `documents`). Each resolves the collection
with `manager.get(name)` and calls `managed.write(...)` or `managed.read(...)`
with a function from `adapter/operations.py`; models live in `models/vectors.py`.

### Writes

```json
{"docs": [
  {"id": "a1", "vectors": {"embedding": [0.1, 0.2, 0.3, 0.4]},
   "fields": {"category": "tech", "year": 2021}},
  {"vectors": {"embedding": [0.9, 0.1, 0.05, 0.02]},
   "fields": {"category": "science", "year": 2019}}
]}
```

```json
{"results": [
   {"id": "a1", "ok": true, "code": "OK", "message": ""},
   {"id": "f1c2...32 hex chars", "ok": true, "code": "OK", "message": ""}],
 "success_count": 2, "error_count": 0}
```

`DocIn`: `id` (string or null), `vectors` (name → list of floats, default `{}`),
`fields` (name → value, default `{}`). Insert adds new documents; upsert inserts
or replaces by id; update modifies existing documents and may send only the fields
being changed. All three go through one adapter function with a `mode` argument
that picks `collection.insert`, `upsert`, or `update`. The engine's per-document
`Status` becomes `WriteResultItem(id, ok, code, message)`.

### Delete

By ids, request and response:

```json
{"ids": ["a1", "a2"]}
```

```json
{"ok": true, "results": [{"id": "a1", "ok": true, "code": "OK", "message": ""},
                         {"id": "a2", "ok": true, "code": "OK", "message": ""}],
 "filter": null, "message": null}
```

By filter, request and response:

```json
{"filter": "category = 'science' AND year < 2020"}
```

```json
{"ok": true, "results": null,
 "filter": "category = 'science' AND year < 2020", "message": "Deleted by filter."}
```

Id deletes call `collection.delete(ids)`; filter deletes call
`delete_by_filter(filter)`, which reports no per-document status. Filters use
Zvec's SQL-like syntax: single `=`, single-quoted strings, `AND`/`OR`/`NOT`,
`IN`, `BETWEEN`, `LIKE`. A malformed filter → `400` with `details.filter`.

### Fetch

```json
{"ids": ["a1", "a2", "missing"], "output_fields": ["category"], "include_vector": false}
```

```json
{"docs": {"a1": {"id": "a1", "score": null, "vectors": null,
                 "fields": {"category": "tech"}}}}
```

`DocOut`: `id`, `score` (null outside search), `vectors` (only when
`include_vector` is true, converted to plain float lists), `fields` (null when
empty). `GET /collections/articles/docs/a1?include_vector=true` builds the same
fetch for one id and returns the bare `DocOut`, or `404 document_not_found` with
`details: {"collection", "id"}`.

### Mapping

`adapter/doc_mapper.py` converts `DocIn` → `zvec.Doc` (generating ids), native
docs → `DocOut`, and statuses → result items. `adapter/operations.py` is the only
module calling Zvec document methods and owns the exception mapping in R8. Neither
takes locks; the manager does.

## Acceptance criteria

- Inserting three documents returns `success_count: 3`, `error_count: 0`, ids in
  input order; a document without `id` gets a 32-char hex id back.
- Insert into an unknown collection → `404 collection_not_found`.
- Fetching `["a", "b", "missing"]` returns exactly `a` and `b`; with
  `include_vector: true` vectors match the input within FP32 precision.
- `GET .../docs/a` returns the document; `GET .../docs/nope` → `404
  document_not_found`.
- Updating `{"id": "a", "fields": {"year": 2099}}` succeeds and a later GET shows
  `year: 2099`; upsert of a new id succeeds.
- Deleting ids `a`, `b` leaves only `c`; deleting by `year < 2020` returns `ok:
  true`; a body with neither or both of `ids`/`filter` → `422`.

## Risks and open questions

- Large batches hold the collection's exclusive lock for the whole batch, stalling
  reads on that collection. No batch size cap in v0.1.0; a proxy body limit is
  the operator's lever.
- Duplicate-id inserts and updates of missing ids surface as per-document non-OK
  statuses inside a `200`, not as `409`/`404`. Clients must check `error_count`.
- Sparse vector dtypes are accepted in schemas (SPEC-002), but `DocIn.vectors`
  only models dense float lists. The wire format for sparse vectors is open.
- Returned vectors reflect storage precision (FP16, INT8), not the input values.
- A filter delete gives no count or per-document detail; clients needing
  confirmation must fetch or search afterwards.

## Tickets

- ZS-014 — Document mapper: REST to zvec.Doc, generated ids, per-doc status
- ZS-015 — Insert, upsert, and update endpoints
- ZS-016 — Delete documents by ids or by filter
- ZS-017 — Fetch documents by ids and get a document by id
