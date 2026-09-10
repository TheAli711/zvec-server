---
id: SPEC-011
title: Index quantization, RaBitQ indexes, and per-index search params
status: draft
created: 2026-09-10
release: v0.2.0
---

# SPEC-011: Index quantization, RaBitQ indexes, and per-index search params

## Summary

Expose the index and query options that Zvec 0.7.0 (SPEC-010) provides:

- scalar quantization (`fp16` / `int8` / `int4`, optional rotation) for `hnsw`,
  `flat`, and `ivf`;
- SOAR spilling for `ivf`;
- two new index types, `hnsw_rabitq` and `ivf_rabitq`;
- query-time tuning for every index type.

Both parameter sets become **strict**. Unknown or mistyped index `params` return
`422`, and unknown or mistyped search `params` return `400`; today both are silently
ignored. No new endpoints are added. The options go through the existing
`vectors[].params` on create and `queries[].params` on search.

## Motivation

- Users want smaller and faster indexes for high-dimensional embeddings, and Zvec
  0.7.0 has quantizers we do not expose.
- The query mapper honors only HNSW `ef`. An IVF collection cannot tune `nprobe`,
  and nothing can request an exact (`is_linear`) scan or a distance `radius`. Our
  own benchmarks can sweep `nprobe` only on the engine tier.
- Both `params` objects accept any keys and silently ignore unknown ones. Once
  quantization lands, a typo such as `quantize` for `quantize_type` would build a
  full-precision index and report success. Silent misconfiguration is worse than an
  error.

## Goals

- Opt-in quantization and rotation per vector field, fixed at create time.
- `use_soar` for `ivf`, plus the RaBitQ index types with their build params.
- Query params for every index type, checked against the field's actual index.
- One validation rule for both `params` objects: unknown keys and wrong JSON types
  are rejected, and the error names the valid keys.
- Quantized and SOAR collections survive a restart with their params intact.

## Non-goals

- Changing the index or quantization of an existing collection. There is no alter
  or reindex; drop and recreate.
- Quantization on by default, or chosen per request.
- Dropping full-precision vectors. Zvec keeps the originals, and fetch keeps
  returning them unchanged.
- RaBitQ as a `quantize_type`. It is a distinct index family with its own params.
- Emulating RaBitQ on platforms the engine does not support.
- Exposing every Zvec knob (e.g. `use_contiguous_memory`) or auto-tuning
  `ef`/`nprobe`.

## Requirements

- **R1.** `hnsw`, `flat`, and `ivf` must accept `params.quantize_type`
  (`fp16`/`int8`/`int4`, case-insensitive) and `params.enable_rotate` (bool).
  `enable_rotate` without `quantize_type` is an error.
- **R2.** `ivf` must accept `params.use_soar` (bool).
- **R3.** `vectors[].index` must accept `hnsw_rabitq` (params `m`,
  `ef_construction`, `total_bits`, `num_clusters`, `sample_count`) and `ivf_rabitq`
  (params `n_list`, `total_bits`, `sample_count`). All are integers. `n_list` keeps
  its API name even though Zvec's RaBitQ kwarg is `nlist`.
- **R4.** On a platform where the engine rejects RaBitQ (anything other than Linux
  x86_64), create must return `422 schema_validation_error` and must not register
  the collection.
- **R5.** Any `params` key not listed for the index type, and any value of the wrong
  type, must return `422 schema_validation_error`. Unknown keys must be reported in
  `details.unknown`, with the allowed keys in `details.valid`.
- **R6.** Search must accept these `queries[].params` per index type. Unknown keys,
  wrong types, and params on a field that does not exist must return
  `400 invalid_argument`.
- **R7.** The query mapper must choose the query-param class from the index type in
  the **open collection's schema**, not from the request or the SQLite snapshot.
- **R8.** The create response and `GET /collections/{name}` must echo the new
  settings in `vectors[].index_param`, and they must be identical after a restart.
- **R9.** Only `zvec_server.adapter.*` may import `zvec`. Models keep `params` as
  a free-form `dict[str, Any]`, and all validation lives in the adapter.
- **R10.** The benchmark runners (SPEC-007) must send only the query param that
  applies to the index under test, so they keep working with strict params.

## Design

### Index params (`adapter/schema_mapper.py`, `adapter/enums.py`)

| Index         | Allowed `params`                                                   |
| ------------- | ------------------------------------------------------------------ |
| `hnsw`        | `m`, `ef_construction`, `quantize_type`, `enable_rotate`           |
| `ivf`         | `n_list`, `n_iters`, `use_soar`, `quantize_type`, `enable_rotate`  |
| `flat`        | `quantize_type`, `enable_rotate`                                   |
| `hnsw_rabitq` | `m`, `ef_construction`, `total_bits`, `num_clusters`, `sample_count` |
| `ivf_rabitq`  | `n_list`, `total_bits`, `sample_count`                             |

- `enums.INDEX_TYPES` gains `hnsw_rabitq` and `ivf_rabitq`. The new
  `enums.QUANTIZE_TYPES = {fp16, int8, int4}` and `parse_quantize_type()` resolve
  a token to `zvec.QuantizeType`.
- The mapper checks keys against a per-index allow-list before building anything.
  `quantize_type` maps to the `quantize_type` kwarg, `enable_rotate` to
  `zvec.QuantizerParam(enable_rotate=...)`, and `use_soar` to
  `IVFIndexParam(use_soar=...)`. RaBitQ builds `HnswRabitqIndexParam` or
  `IvfRabitqIndexParam`.
- `adapter/collections.create_collection` maps the engine's `RuntimeError` "... not
  supported on this platform" to `SchemaValidationError`.

`POST /collections` request, and the `vectors[0].index_param` excerpt echoed in the
`201` response (Zvec fills in defaults such as `ef_construction`):

```json
{ "name": "articles",
  "vectors": [{ "name": "embedding", "dim": 768, "index": "hnsw",
                "params": { "m": 16, "quantize_type": "int8", "enable_rotate": true } }] }
```

```json
{ "type": "HNSW", "metric_type": "COSINE", "m": 16, "ef_construction": 500,
  "quantize_type": "INT8", "quantizer_param": { "enable_rotate": true } }
```

An unknown key (here `quantize` instead of `quantize_type`) returns `422`:

```json
{ "error": { "code": "schema_validation_error",
    "message": "Unknown parameter(s) for 'hnsw' index: quantize",
    "details": { "unknown": ["quantize"],
                 "valid": ["ef_construction", "enable_rotate", "m", "quantize_type"] } } }
```

### Query params (`adapter/query_mapper.py`, `adapter/operations.py`)

| Index                 | Allowed `queries[].params`                                        |
| --------------------- | ----------------------------------------------------------------- |
| `hnsw`, `hnsw_rabitq` | `ef` int, `radius` float, `is_linear` bool, `is_using_refiner` bool |
| `ivf`                 | `nprobe` int                                                      |
| `ivf_rabitq`          | `nprobe`, `radius`, `is_linear`, `is_using_refiner`, `scale_factor` float |
| `flat`                | none                                                              |

- `vector_index_types(collection)` maps field name to index type name, read from
  `collection.schema.vectors`. `operations.search` passes the result to
  `build_queries(specs, index_types)` under the read lock.
- Type rules: `bool` must be a JSON boolean, `int` must be an integer and not a
  bool, and `float` accepts any JSON number. The mapper builds `HnswQueryParam`,
  `HnswRabitqQueryParam`, `IVFQueryParam`, or `IvfRabitqQueryParam`. Omitting
  `params` leaves the engine defaults.

`POST /collections/articles/search` on an `hnsw` field, and the `400` returned
when the same `ef` is sent to a `flat` field:

```json
{ "queries": [{ "field": "embedding", "vector": [0.1, 0.2, 0.3, 0.4],
                "params": { "ef": 128, "is_using_refiner": true } }], "topk": 10 }
```

```json
{ "error": { "code": "invalid_argument",
    "message": "Unknown query parameter(s) for flat field 'embedding': ef",
    "details": { "field": "embedding", "unknown": ["ef"], "valid": [] } } }
```

### Layers and docs

The API and manager are unchanged. Models change only in their field descriptions
(OpenAPI). Benchmarks get a `server_query_params(index, ef=, nprobe=)` helper that
the `inproc` and `http` runners share. Docs: the index-type table, param tables, a
quantization paragraph and example in `docs/API.md`, CHANGELOG entries (including
the breaking strictness change), and README key features.

## Acceptance criteria

- Each of `hnsw`/`flat`/`ivf` × `fp16`/`int8`/`int4` with `enable_rotate` builds,
  and `index_param` shows the quantize type and rotation. A quantized collection
  returns correct nearest neighbours after optimize.
- Bad quantize values (`int2`, `rabitq`, a number, rotation without a type, a
  non-bool `enable_rotate`) return 422.
- Keys that belong to another index type (`n_list` on hnsw, `m` on flat) and typos
  return 422 with `unknown`/`valid` details.
- RaBitQ collections create, optimize, and search on Linux x86_64. Elsewhere,
  create returns 422 and `GET` returns 404.
- Search params work for hnsw (`ef`, `radius`, `is_linear`, `is_using_refiner`) and
  ivf (`nprobe`). `ef` on flat or ivf, `nprobe` on hnsw, `"ef": "64"`,
  `"is_linear": 1`, and params on an unknown field all return 400.
- Quantized-HNSW and SOAR-IVF collections reopen after a restart with identical
  `vectors`, the same doc count, and working `ef`/`nprobe` searches.

## Risks and open questions

- **Breaking change.** Clients that send ignored params (e.g. `ef` to a flat field)
  will start getting 400s or 422s. Call this out in the CHANGELOG and ship it in a
  minor release.
- **Unmeasured trade-off.** Zvec keeps full-precision vectors next to the
  quantized index, so disk may not shrink by 2×/4×/8×. The recall, disk, and memory
  cost on real datasets should be benchmarked before we recommend quantization.
- **Platform detection by message.** RaBitQ support is detected by matching the
  engine's error text. A reworded upstream message would turn 422s into 500s. Tests
  assert on the message.
- **CI coverage.** RaBitQ's success path runs only on Linux x86_64 runners. macOS
  developers exercise only the 422 path.
- **Cost of `is_linear`.** It forces a brute-force scan. It stays opt-in per query
  and is documented as exact but slow.
