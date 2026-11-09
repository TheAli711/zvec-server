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

**Index types** (for `vectors[].index`): `hnsw` (default), `flat`, `ivf`,
`hnsw_rabitq`, `ivf_rabitq`. The RaBitQ variants use RaBitQ quantization. The
engine supports them on Linux and macOS (x86_64 and ARM64) and on Windows
x86_64; on any other platform, creating one returns `422`. They have not been
benchmarked here yet.

Optional per-index tuning goes in `vectors[].params`. Unknown keys return `422`.

| Index  | Recognized params                                                         |
| ------ | ------------------------------------------------------------------------- |
| `hnsw` | `m`, `ef_construction`, plus quantization and PQ settings (below)         |
| `ivf`  | `n_list`, `n_iters`, `use_soar`, plus quantization and PQ settings (below) |
| `flat` | quantization only (`quantize_type`, `enable_rotate`)                      |
| `hnsw_rabitq` | `m`, `ef_construction`, `total_bits`, `num_clusters`, `sample_count` |
| `ivf_rabitq`  | `n_list`, `total_bits`, `sample_count` |

**Quantization.** `quantize_type` makes the index search over compressed vectors.
Zvec keeps the original full-precision vectors alongside, and fetch returns them
unchanged, so the quantized index is **extra** storage, not a replacement. The
settings are fixed when the collection is created.

| `quantize_type`                                    | Indexes             | Requirements                     |
| -------------------------------------------------- | ------------------- | -------------------------------- |
| `fp16`, `int8`, `int4`                             | `hnsw`, `flat`, `ivf` | —                              |
| `uniform_uint8`, `uniform_uint7`, `uniform_uint4`  | `hnsw`              | metric `l2`; no `enable_rotate`  |
| `pq` (product quantization)                        | `hnsw`, `ivf`       | dtype `VECTOR_FP32`              |

- `enable_rotate: true` applies a random rotation before `int8`/`int4`
  quantization. With `pq`, it learns an OPQ rotation instead. Other quantize
  types don't support it and return `422`.
- **Not on `hnsw` with `int8`/`int4`, for now.** Zvec 0.8.0 and 0.8.1 return
  near-random results after `optimize` for a new HNSW index with scalar
  quantization and rotation
  ([alibaba/zvec#886](https://github.com/alibaba/zvec/issues/886)), so the
  server rejects that combination with `422`.
  `flat`/`ivf` with rotation and `hnsw` with `pq` + OPQ are unaffected, and so
  are HNSW collections created before the upgrade.
- The uniform quantizers share one value range across all vectors. That makes
  scoring cheaper but can cost recall. Pair them with the search-time refiner
  (below).
- PQ settings, accepted only with `quantize_type: "pq"`:

  | Param         | Type        | Default | Notes                                                        |
  | ------------- | ----------- | ------- | ------------------------------------------------------------ |
  | `num_chunk`   | int         | 8       | Sub-quantizers, 1..`dim`. More chunks keep more information. |
  | `num_bits`    | 4 or 8      | 8       | Bits per code.                                               |
  | `fast_scan`   | bool        | `false` | `ivf` only, with `num_bits: 4` and a `num_chunk` that divides `dim`. Packed SIMD scan. |
  | `opq_iter`    | int 1–100   | 5       | OPQ iterations. Requires `enable_rotate: true`.              |
  | `opq_pq_iter` | int 1–100   | 4       | PQ iterations per OPQ iteration. Requires `enable_rotate: true`. |

  PQ learns its codebook during `optimize`. Until the first optimize, searches
  scan the vectors exactly.

> **Measure before adopting.** SIFT1M (1M × 128, L2), HNSW `m=16`,
> `ef_construction=200`, mmap on, searching at `ef=200` with 16 concurrent
> clients. Zvec 0.8.1 on an Apple M5, engine tier:
>
> | `quantize_type` | disk vs fp32 | recall@10 | + refiner (`scale_factor` 0) | QPS vs fp32 | + refiner |
> | --------------- | -----------: | --------: | ---------------------------: | ----------: | --------: |
> | none (fp32)     | 687 MB       | 0.996     | —                            | 21.3k       | —         |
> | `fp16`          | +38%         | 0.996     | 0.996                        | +13%        | −49%      |
> | `int8`          | +20%         | 0.987     | 0.995                        | +25%        | −48%      |
> | `int4`          | +11%         | 0.867     | 0.996                        | −5%         | −49%      |
> | `uniform_uint8` | +20%         | 0.995     | 0.995                        | +20%        | −48%      |
> | `uniform_uint7` | +20%         | 0.965     | 0.995                        | +22%        | −49%      |
> | `uniform_uint4` | +11%         | 0.834     | 0.994                        | +16%        | −50%      |
> | `pq` (32 × 8-bit) | +7%        | 0.717     | 0.991                        | +20%        | −48%      |
> | `pq` (32 × 4-bit) | +2%        | 0.400     | 0.922                        | +18%        | −52%      |
>
> - **Disk and memory grow.** Every variant uses more disk than fp32, because
>   Zvec keeps the full-precision vectors, and server memory was the same or
>   higher. On this engine version quantization buys **speed**, not space.
> - **`uniform_uint8` is the one free win.** It matches fp32 recall and runs
>   about 20% faster, with no refiner needed.
> - **The refiner restores recall but halves throughput at `scale_factor` 0**,
>   because it re-scores max(`topk`, `ef`) = 200 candidates. A small window is
>   much cheaper: for `pq`, `scale_factor: 5` gave 0.984 recall at +11% QPS, and
>   `2` gave 0.908 at +17%. Start around 3–5 and tune.
> - **PQ needs the refiner.** OPQ (`enable_rotate: true`) lowered PQ recall on
>   SIFT (0.623 vs 0.717) and slowed optimize (66 s vs 56 s, against 47 s for
>   fp32). The other variants optimize faster than fp32 (31–37 s).
>
> Results differ for other data and hardware, and SIFT is low-dimensional by
> modern embedding standards. Run the sweep on your own data with
> `python -m benchmarks quant` (see `benchmarks/README.md`).

```json
{ "name": "embedding", "dim": 768, "index": "ivf", "metric": "l2",
  "params": { "n_list": 1024, "quantize_type": "pq", "num_chunk": 96,
              "num_bits": 4, "fast_scan": true } }
```

`index_param` in the create response and in `GET /collections/{name}` echoes the
effective settings, including every `quantizer_param` default
(`enable_rotate`, `num_chunk`, `num_bits`, `fast_scan`, `opq_iter`,
`opq_pq_iter`).

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
| `name`            | string                   | yes      | Matches `^[A-Za-z0-9_-]{3,64}$`.                     |
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
| `index`  | string          | `hnsw`          | See [index types](#index-types--metrics). |
| `metric` | string          | `cosine`        | `cosine` / `ip` / `l2`.                |
| `params` | object \| null  | `null`          | Index tuning params.                   |

`ScalarFieldSpec`:

| Field      | Type    | Default | Notes                                   |
| ---------- | ------- | ------- | --------------------------------------- |
| `name`     | string  | —       | Scalar field name: ASCII, up to 64 bytes. |
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

**Document ids** can be any non-empty UTF-8 string of up to 1,024 bytes without
a NUL or newline character, so URLs, paths, and titles work as-is. An invalid id
returns `400`. Omit `id` on insert to get a random hex UUID. HTTP clients
normalize the path segments `.` and `..`, so to fetch an id like that, use
`POST /docs/fetch`, or encode its dots as `%2E`.

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
URL-encode the id. Ids that contain `/` work both encoded (`%2F`) and literally.

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

### `GET /collections/{name}/export`

Stream **every** document as NDJSON (`application/x-ndjson`, one JSON object
per line) — for backups, migrations, or re-indexing. Each line is shaped like a
`DocIn` (`id`, `vectors`, `fields`; no `score`), so an export can be posted back
to `/docs/insert` in batches unchanged.

| Query param      | Type                  | Default | Notes                                   |
| ---------------- | --------------------- | ------- | --------------------------------------- |
| `include_vector` | bool                  | `true`  | Include vectors (needed to re-import).  |
| `output_fields`  | string (repeatable)   | all     | Restrict scalar fields, e.g. `?output_fields=year`. |

```bash
curl -s localhost:8000/collections/articles/export > articles.ndjson
```

```
{"id":"a1","vectors":{"embedding":[0.1,0.2,0.3,0.4]},"fields":{"category":"tech","year":2021}}
{"id":"a2","vectors":{"embedding":[0.2,0.1,0.0,0.9]},"fields":{"category":"news","year":2019}}
```

- **Consistent snapshot.** The export reflects the collection as of the
  request; writes made while it streams are not included, and are **not
  blocked** by it (the collection lock is taken per batch, not for the whole
  stream).
- **Errors.** Bad input (unknown `output_fields`, missing collection) returns a
  normal JSON error before streaming starts. If the export is cut short after
  it has started — e.g. the collection is dropped or the server shuts down —
  the **last line is an error envelope** (`{"error": {...}}`) instead of a
  document. Check for it before treating an export as complete.
- Order is unspecified.

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
| `params` | object \| null        | Query tuning for the field's index (below). |

Query `params` by index type (unknown keys return `400`):

| Index                  | Params                                                        |
| ---------------------- | ------------------------------------------------------------- |
| `hnsw`, `hnsw_rabitq`  | `ef` (int), `radius` (float), `is_linear` (bool), `is_using_refiner` (bool), `scale_factor` (float) |
| `ivf`                  | `nprobe` (int), `is_using_refiner` (bool), `scale_factor` (float) |
| `ivf_rabitq`           | `nprobe`, `radius`, `is_linear`, `is_using_refiner`, `scale_factor` |
| `flat`                 | none                                                          |

- `ef` and `nprobe` trade speed for recall.
- `is_linear: true` forces an exact brute-force scan.
- `radius` limits hits to a distance threshold.

**Refiner.** `is_using_refiner: true` re-scores a larger candidate set against
the full-precision vectors, which recovers most of the recall that quantization
loses. `scale_factor` (0–1000) sizes that candidate set, and the defaults
differ by index:

- on `hnsw`, `0` (the default) means max(`topk`, `ef`) candidates;
- on `ivf`, the default is `10` (`topk` × 10).

On `hnsw`, the refiner requires a quantized index (`quantize_type` set), and
otherwise returns `400`.

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

### `POST /collections/{name}/search/group-by`

Run **one** query, bucket hits by the value of a scalar field, and return the
best `topk_per_group` hits from each of the best `group_count` groups. Typical
RAG use: chunks stored with a `doc_id` field, grouped so one long document
can't crowd every other document out of the results.

| Field            | Type                    | Default | Notes                                      |
| ---------------- | ----------------------- | ------- | ------------------------------------------ |
| `query`          | `QuerySpec`             | —       | Same shape as a `search` query.            |
| `group_by`       | string                  | —       | Scalar field defining the groups.          |
| `group_count`    | int (1–1000)            | `10`    | Maximum groups returned.                   |
| `topk_per_group` | int (1–1000)            | `3`     | Maximum hits per group.                    |
| `filter`         | string \| null          | `null`  | SQL-like scalar filter.                    |
| `include_vector` | bool                    | `false` | Include vectors in hits.                   |
| `output_fields`  | array of string \| null | `null`  | Restrict returned scalar fields.           |

**Example request**

```json
{
  "query": { "field": "embedding", "vector": [0.12, 0.22, 0.29, 0.41] },
  "group_by": "doc_id",
  "group_count": 5,
  "topk_per_group": 2
}
```

**Response 200** (`GroupSearchResponse`)

```json
{
  "groups": [
    { "value": "doc-7", "results": [{ "id": "doc-7#3", "score": 0.011, "fields": { "doc_id": "doc-7" } }] },
    { "value": "doc-2", "results": [{ "id": "doc-2#0", "score": 0.019, "fields": { "doc_id": "doc-2" } }] }
  ]
}
```

> Group `value`s are always strings (an `INT64` field's `3` comes back as
> `"3"`), and documents with a null `group_by` value form a group with value
> `""`. An unknown `group_by` field or a malformed filter returns `400`.
