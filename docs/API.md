# REST API Reference

Base URL (default): `http://localhost:8000`

All request and response bodies are JSON (`Content-Type: application/json`).
Interactive, always-up-to-date docs are served by the running server at `/docs`
(Swagger UI) and `/redoc` (ReDoc); the OpenAPI schema is at `/openapi.json`.

## Contents

- [Conventions](#conventions)
- [Authentication](#authentication)
- [Errors](#errors)
- [Filter syntax](#filter-syntax)
- [Data types](#data-types)
- [Index types & metrics](#index-types--metrics)
- [Health](#health)
- [Collections](#collections)
- [Documents](#documents)
- [Search](#search)

---

## Conventions

- Document **ids are always strings**. If you omit `id` on insert/upsert, the
  server generates one (a UUID hex) and returns it in the write results.
- A document has named **vector fields** (`vectors`) and named **scalar fields**
  (`fields`). The vector field names must match the collection schema.
- The server stores **client-supplied vectors only**. It does not generate
  embeddings.

---

## Authentication

Authentication is **off by default**. When the server is started with
`ZVEC_SERVER_AUTH_ENABLED=true` and a `ZVEC_SERVER_API_KEY`, every endpoint
**except** the health probes (`/healthz`, `/readyz`) requires the key as a bearer
token:

```http
Authorization: Bearer <api_key>
```

```bash
curl http://localhost:8000/collections \
  -H "Authorization: Bearer $ZVEC_SERVER_API_KEY"
```

A missing or invalid key returns `401 Unauthorized` with the standard error
envelope (`code: "unauthorized"`) and a `WWW-Authenticate: Bearer` response
header. When auth is enabled, the interactive docs (`/docs`, `/openapi.json`)
also require the key. See
[CONFIGURATION.md](./CONFIGURATION.md#authentication).

---

## Errors

Errors use a consistent envelope:

```json
{
  "error": {
    "code": "collection_not_found",
    "message": "Collection 'articles' not found.",
    "details": { "name": "articles" }
  }
}
```

`code` is a stable, machine-readable string (snake_case); `details` is optional.
Status codes and their `code` values:

| Status | `code`                     | When                                                                |
| ------ | -------------------------- | ------------------------------------------------------------------- |
| 400    | `invalid_argument`         | Argument rejected by the server or engine (e.g. a malformed filter).|
| 401    | `unauthorized`             | Auth enabled and the API key was missing or invalid.                |
| 404    | `collection_not_found`     | No such collection.                                                 |
| 404    | `document_not_found`       | No such document (single-document fetch).                           |
| 409    | `collection_already_exists`| A collection with that name already exists.                         |
| 422    | `schema_validation_error`  | Invalid schema (bad dtype/index/metric).                            |
| 422    | `validation_error`         | Request body failed validation (`ids`+`filter` both/neither, etc.). |
| 500    | `zvec_operation_error` / `internal_error` | Unexpected server / Zvec engine error.               |
| 503    | `collection_unavailable`   | Collection registered but not currently open on disk.               |

---

## Filter syntax

The `filter` string used by **search** and **delete-by-filter** uses Zvec's
**SQL-like** expression syntax. It is passed through to Zvec **verbatim**.

- Use a single `=` for equality — **not** Python's `==`.
- Quote string literals with **single quotes**: `'tech'`.
- Operators: `=`, `<`, `>`, `<=`, `>=`, `AND`, `OR`, `NOT`, `IN`, `BETWEEN`, `LIKE`.

Examples:

```text
category = 'tech'
category = 'tech' AND year > 2020
year BETWEEN 2018 AND 2022
category IN ('tech', 'science')
NOT (category = 'sports')
title LIKE 'intro%'
```

A malformed filter results in a `400` (`invalid_argument`).

---

## Data types

Provide dtypes by name (case-sensitive, as Zvec defines them).

**Vector dtypes** (for `vectors[].dtype`):

| Name                 | Meaning                          |
| -------------------- | -------------------------------- |
| `VECTOR_FP32`        | 32-bit float dense vector (default). |
| `VECTOR_FP16`        | 16-bit float dense vector.       |
| `VECTOR_FP64`        | 64-bit float dense vector.       |
| `VECTOR_INT8`        | 8-bit int dense vector.          |
| `SPARSE_VECTOR_FP16` | 16-bit float sparse vector.      |
| `SPARSE_VECTOR_FP32` | 32-bit float sparse vector.      |

**Scalar dtypes** (for `fields[].dtype`):

| Name                  | Meaning                       |
| --------------------- | ----------------------------- |
| `INT32`, `INT64`      | Signed integers.              |
| `UINT32`, `UINT64`    | Unsigned integers.            |
| `FLOAT`, `DOUBLE`     | Floating point.               |
| `STRING`              | Text.                         |
| `BOOL`                | Boolean.                      |
| `ARRAY_*`             | Array variants of the above.  |

---

## Index types & metrics

**Index types** (for `vectors[].index`): `hnsw` (default), `flat`, `ivf`.

Optional per-index tuning goes in `vectors[].params`:

| Index  | Recognized params                  |
| ------ | ---------------------------------- |
| `hnsw` | `m`, `ef_construction`             |
| `ivf`  | `n_list`, `n_iters`               |
| `flat` | (none)                             |

**Metrics** (for `vectors[].metric`): `cosine` (default), `ip` (inner product),
`l2` (Euclidean). Aliases such as `dot` / `inner_product` and `euclidean` are
accepted.

---

## Health

### `GET /healthz`

Liveness probe.

**Response 200**

```json
{ "status": "ok" }
```

### `GET /readyz`

Readiness probe with collection counts.

**Response 200**

```json
{
  "status": "ready",
  "collections_loaded": 2,
  "collections_unavailable": 0
}
```

---

## Collections

### `POST /collections`

Create a collection.

**Request body** (`CreateCollectionRequest`):

| Field             | Type                     | Required | Notes                                                |
| ----------------- | ------------------------ | -------- | ---------------------------------------------------- |
| `name`            | string                   | yes      | Matches `^[A-Za-z0-9_-]{1,128}$`.                    |
| `vectors`         | array of `VectorFieldSpec` | yes    | At least one.                                        |
| `fields`          | array of `ScalarFieldSpec` | no     | Defaults to `[]`.                                    |
| `options`         | object                   | no       | `{ "enable_mmap": bool }`.                           |
| `embedding_model` | string \| null           | no       | Free-form metadata label only; not used to compute embeddings. |

`VectorFieldSpec`:

| Field    | Type            | Default         | Notes                                  |
| -------- | --------------- | --------------- | -------------------------------------- |
| `name`   | string          | —               | Vector field name.                     |
| `dim`    | int (> 0)       | —               | Vector dimension.                      |
| `dtype`  | string          | `VECTOR_FP32`   | See [data types](#data-types).         |
| `index`  | string          | `hnsw`          | `hnsw` / `flat` / `ivf`.               |
| `metric` | string          | `cosine`        | `cosine` / `ip` / `l2`.                |
| `params` | object \| null  | `null`          | Index tuning params.                   |

`ScalarFieldSpec`:

| Field      | Type    | Default | Notes                                   |
| ---------- | ------- | ------- | --------------------------------------- |
| `name`     | string  | —       | Scalar field name.                      |
| `dtype`    | string  | —       | See [scalar dtypes](#data-types).       |
| `nullable` | bool    | `false` | Whether the field may be null.          |
| `indexed`  | bool    | `false` | Build an inverted index (faster filters). |

**Example request**

```json
{
  "name": "articles",
  "vectors": [
    {
      "name": "embedding",
      "dim": 4,
      "dtype": "VECTOR_FP32",
      "index": "hnsw",
      "metric": "cosine",
      "params": { "m": 16, "ef_construction": 200 }
    }
  ],
  "fields": [
    { "name": "category", "dtype": "STRING", "indexed": true },
    { "name": "year", "dtype": "INT32", "indexed": true }
  ],
  "options": { "enable_mmap": true }
}
```

**Response 201** (`CollectionInfo`)

```json
{
  "name": "articles",
  "path": "/data/collections/articles",
  "schema_version": 1,
  "embedding_dimension": 4,
  "embedding_model": null,
  "vectors": [
    { "name": "embedding", "data_type": "VECTOR_FP32", "dimension": 4 }
  ],
  "fields": [
    { "name": "category", "data_type": "STRING", "nullable": false },
    { "name": "year", "data_type": "INT32", "nullable": false }
  ],
  "options": { "enable_mmap": true },
  "stats": { "doc_count": 0, "index_completeness": {} },
  "available": true,
  "created_at": "2026-06-23T12:00:00+00:00",
  "updated_at": "2026-06-23T12:00:00+00:00"
}
```

> `409` (`collection_already_exists`) if a collection with that name exists.
> `422` (`schema_validation_error`) for an invalid dtype/index/metric or bad name.

### `GET /collections`

List collections.

**Response 200** (`CollectionListResponse`)

```json
{
  "collections": [
    {
      "name": "articles",
      "embedding_dimension": 4,
      "embedding_model": null,
      "doc_count": 3,
      "created_at": "2026-06-23T12:00:00+00:00"
    }
  ]
}
```

### `GET /collections/{name}`

Get full collection info, including live stats. Returns the same
`CollectionInfo` shape as create. `404` if not found.

### `DELETE /collections/{name}`

Drop a collection. This **deletes its data on disk**.

**Response 200** (`MessageResponse`)

```json
{ "message": "Collection 'articles' deleted" }
```

### `POST /collections/{name}/flush`

Flush pending writes to disk.

**Response 200** (`MessageResponse`)

```json
{ "message": "Collection 'articles' flushed" }
```

### `POST /collections/{name}/optimize`

Optimize the collection's indexes.

**Response 200** (`MessageResponse`)

```json
{ "message": "Collection 'articles' optimized" }
```

---

## Documents

All document endpoints are under `/collections/{name}`.

### `POST /collections/{name}/docs/insert`

Insert documents. Use `upsert` to insert-or-replace and `update` to modify
existing documents; all three share the `WriteRequest` body and `WriteResponse`
shape.

**Request body** (`WriteRequest`):

```json
{
  "docs": [
    {
      "id": "a1",
      "vectors": { "embedding": [0.10, 0.20, 0.30, 0.40] },
      "fields": { "category": "tech", "year": 2021 }
    },
    {
      "vectors": { "embedding": [0.90, 0.10, 0.05, 0.02] },
      "fields": { "category": "science", "year": 2019 }
    }
  ]
}
```

`DocIn`:

| Field     | Type                          | Default | Notes                                       |
| --------- | ----------------------------- | ------- | ------------------------------------------- |
| `id`      | string \| null                | `null`  | Auto-generated if omitted.                  |
| `vectors` | object (name → list of float) | `{}`    | Keys must match the schema's vector fields. |
| `fields`  | object (name → value)         | `{}`    | Scalar field values.                        |

**Response 200** (`WriteResponse`)

```json
{
  "results": [
    { "id": "a1", "ok": true, "code": "OK", "message": "" },
    { "id": "f1c2...hex", "ok": true, "code": "OK", "message": "" }
  ],
  "success_count": 2,
  "error_count": 0
}
```

### `POST /collections/{name}/docs/upsert`

Insert or replace documents. Same body/response as `insert`.

### `POST /collections/{name}/docs/update`

Update existing documents. Same body/response as `insert`.

### `POST /collections/{name}/docs/delete`

Delete by **either** `ids` **or** `filter` — exactly one must be set
(`422` otherwise).

**Request body** (`DeleteRequest`) — by ids:

```json
{ "ids": ["a1", "a2"] }
```

By filter (see [filter syntax](#filter-syntax)):

```json
{ "filter": "category = 'science' AND year < 2020" }
```

**Response 200** (`DeleteResponse`) — by ids:

```json
{
  "ok": true,
  "results": [
    { "id": "a1", "ok": true, "code": "OK", "message": "" },
    { "id": "a2", "ok": true, "code": "OK", "message": "" }
  ],
  "filter": null,
  "message": null
}
```

By filter:

```json
{
  "ok": true,
  "results": null,
  "filter": "category = 'science' AND year < 2020",
  "message": null
}
```

> A malformed filter returns `400` (`invalid_argument`).

### `POST /collections/{name}/docs/fetch`

Fetch documents by id. Missing ids are simply omitted from the result map.

**Request body** (`FetchRequest`):

```json
{
  "ids": ["a1", "a2"],
  "output_fields": ["category", "year"],
  "include_vector": false
}
```

| Field            | Type                | Default | Notes                                 |
| ---------------- | ------------------- | ------- | ------------------------------------- |
| `ids`            | array of string     | —       | At least one.                         |
| `output_fields`  | array of string \| null | `null` | Restrict returned scalar fields.  |
| `include_vector` | bool                | `false` | Include vector values in the result.  |

**Response 200** (`FetchResponse`)

```json
{
  "docs": {
    "a1": {
      "id": "a1",
      "score": null,
      "vectors": null,
      "fields": { "category": "tech", "year": 2021 }
    }
  }
}
```

### `GET /collections/{name}/docs/{doc_id}`

Fetch a single document by id. Returns `404` (`document_not_found`) if missing.

**Query parameters**

| Name             | Type                | Default | Notes                              |
| ---------------- | ------------------- | ------- | ---------------------------------- |
| `include_vector` | bool                | `false` | Include vector values.             |
| `output_fields`  | repeated string     | (all)   | Restrict returned scalar fields.   |

**Example**

```
GET /collections/articles/docs/a1?include_vector=true
```

**Response 200** (`DocOut`)

```json
{
  "id": "a1",
  "score": null,
  "vectors": { "embedding": [0.10, 0.20, 0.30, 0.40] },
  "fields": { "category": "tech", "year": 2021 }
}
```

---

## Search

### `POST /collections/{name}/search`

Vector similarity search. Each query searches by an explicit `vector` **or** by
an existing document `id` (exactly one per query).

**Request body** (`SearchRequest`):

| Field            | Type                     | Default | Notes                                       |
| ---------------- | ------------------------ | ------- | ------------------------------------------- |
| `queries`        | array of `QuerySpec`     | —       | At least one.                               |
| `topk`           | int (1–1000)             | `10`    | Number of results per query.                |
| `filter`         | string \| null           | `null`  | SQL-like scalar filter (see above).         |
| `include_vector` | bool                     | `false` | Include vectors in hits.                    |
| `output_fields`  | array of string \| null  | `null`  | Restrict returned scalar fields.            |

`QuerySpec` (exactly one of `vector` / `id`):

| Field    | Type                  | Notes                                  |
| -------- | --------------------- | -------------------------------------- |
| `field`  | string                | Vector field to search.                |
| `vector` | list of float \| null | Query vector.                          |
| `id`     | string \| null        | Search by an existing document's vector. |
| `params` | object \| null        | Query tuning, e.g. `{ "ef": 64 }` (hnsw). |

**Example request**

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

**Response 200** (`SearchResponse`)

```json
{
  "results": [
    {
      "id": "a1",
      "score": 0.0123,
      "vectors": null,
      "fields": { "category": "tech", "year": 2021 }
    }
  ]
}
```

> Results are a flat list of hits. For a single query they are ordered by score.
> A malformed filter returns `400` (`invalid_argument`).
