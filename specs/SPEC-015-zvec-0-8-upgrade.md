---
id: SPEC-015
title: Upgrade to Zvec 0.8.1 with uniform and PQ quantizers, refiner, and relaxed ids
status: accepted
created: 2026-11-09
release: v0.3.0
---

# SPEC-015: Upgrade to Zvec 0.8.1 with uniform and PQ quantizers, refiner, and relaxed ids

## Summary

Raise the engine floor from `zvec>=0.7.0` to `zvec>=0.8.1` and expose the 0.8
features that fit a storage layer:

- the uniform quantizers (`uniform_uint4` / `uniform_uint7` / `uniform_uint8`)
  for `hnsw`, and product quantization (`pq`, with optional OPQ and IVF
  FastScan) for `hnsw` and `ivf`;
- the query-time refiner on every index that has one, so a compressed index can
  re-rank its candidates against the full-precision vectors;
- Zvec's relaxed identifier rules: UTF-8 document ids up to 1,024 bytes and field
  names up to 64 bytes.

The server also guards against a Zvec 0.8 regression: HNSW with a scalar
quantizer and `enable_rotate` returns near-random results after optimize. That
combination is rejected at create time until upstream fixes it. No endpoints are
added; everything goes through the existing `vectors[].params` and
`queries[].params`.

## Motivation

- **Engine fixes we need.** 0.8.0 fixes crashes and missing rows when `fetch()` or
  `query()` races a segment switch or flush. The server runs reads and writes
  concurrently on the same collection, so it can hit exactly this. 0.8.x also fixes
  filter correctness (`LIKE` prefix/suffix overlap, deep `OR` trees, exclusive
  float bounds, empty-array and suffix inverted-index queries, filtered IVF), and
  it releases collection locks held through inherited file descriptors.
- **Compression that keeps recall.** Our 0.7.0 SIFT1M measurements (docs/API.md)
  showed scalar quantization costing disk and memory without a speed gain. 0.8
  adds PQ, which compresses far harder, and a refiner that restores recall by
  re-scoring candidates. In a synthetic check (64-d Gaussian, 2k docs), PQ alone
  gave recall@10 of 0.36–0.67, and with the refiner it reached 1.00.
- **RaBitQ everywhere.** RaBitQ now runs on Linux and macOS ARM64 and Intel Mac,
  as well as Linux x86_64. The "Linux x86_64 only" caveat no longer holds.
- **Ids.** 0.7.0 rejected document ids longer than 64 characters or outside a
  narrow ASCII set (no spaces, `/`, `,`, `'` or non-ASCII). Applications keyed by
  URLs, paths, or natural-language titles had to hash their keys.

## Goals

- `zvec>=0.8.1`, with existing 0.7.0 collections opening and searching unchanged.
- The four new quantizer types and the PQ settings, validated by the server with
  clear `422`s, including combinations that Zvec rejects with misleading or
  generic errors.
- Refiner params on `hnsw`, `hnsw_rabitq`, and `ivf` searches, with a `400`
  (not a `500`) when the refiner can't apply.
- Document ids with any UTF-8 content Zvec accepts, including through
  `GET /collections/{name}/docs/{doc_id}`.
- Measured recall, disk, memory, and latency for the new quantizers on SIFT1M.

## Non-goals

- `VECTOR_UINT8` as a field type. Zvec 0.8.1 lists it in `DataType`, but rejects it
  as a vector field type on every index. It only exists as the refiner's internal
  storage format.
- Relaxing collection names. Zvec now allows UTF-8 names up to 256 bytes, but each
  name becomes a directory on disk and a URL segment. We keep
  `^[A-Za-z0-9_-]{3,64}$`.
- Full-text search, DiskANN, Vamana, `query_internal_ids`, and the HNSW memory
  layout knobs (`use_contiguous_memory`, `flat_data_type`). Each is a separate
  spec if wanted.
- Changing an existing collection's quantization. There is still no reindex.
- Working around the HNSW + rotation bug ourselves, for example by silently
  dropping `enable_rotate`. We reject the request and say why.

## Requirements

- **R1.** `pyproject.toml` requires `zvec>=0.8.1`. Collections written by 0.7.0
  open, search, accept writes, and re-optimize under 0.8.1.
- **R2.** `quantize_type` accepts `uniform_uint4`, `uniform_uint7`,
  `uniform_uint8` on `hnsw` with metric `l2`, and `pq` on `hnsw` and `ivf` with a
  `VECTOR_FP32` field. Any other index, metric, or dtype returns `422` naming the
  supported ones.
- **R3.** PQ settings `num_chunk` (int, 1..dim), `num_bits` (4 or 8), `fast_scan`
  (bool; `ivf` with `num_bits: 4` only, and `num_chunk` must divide `dim`),
  `opq_iter` and `opq_pq_iter` (ints 1..100; require `enable_rotate: true`) are accepted only with `quantize_type: "pq"`.
  `enable_rotate` with `pq` means learned OPQ.
- **R4.** `enable_rotate: true` is accepted only with `int8`, `int4`, or `pq`
  (OPQ). Zvec can't rotate other types: with `fp16`, every insert fails, and with
  a uniform quantizer the create fails (ZS-077). On `hnsw`, `int8`/`int4` with
  rotation return `422` citing the upstream bug, while `pq` + OPQ stays allowed.
- **R5.** Search accepts `scale_factor` (finite number, 0..1000) on `hnsw` and `hnsw_rabitq`,
  and `is_using_refiner` + `scale_factor` on `ivf`. `ivf_rabitq` is unchanged.
- **R6.** `is_using_refiner: true` on an `hnsw` field without quantization returns
  `400 invalid_argument`. Today the engine fails after optimize and the server
  returns `500`.
- **R7.** Document ids follow Zvec's rule (non-empty UTF-8, at most 1,024 bytes, no
  NUL or newline). The server adds no stricter rule, an invalid id still returns
  `400`, and `GET /docs/{doc_id}` matches ids that contain `/`.
- **R8.** `vectors[].index_param` echoes every new setting (Zvec now reports all
  six `quantizer_param` keys), unchanged across a restart.
- **R9.** Only `zvec_server.adapter.*` imports `zvec`. Validation lives in the
  adapter mappers, and models keep free-form `params`.

## Design

### Index params (`adapter/enums.py`, `adapter/schema_mapper.py`)

| Index  | `quantize_type`                                    | PQ keys                                                    |
| ------ | -------------------------------------------------- | ---------------------------------------------------------- |
| `hnsw` | `fp16`, `int8`, `int4`, `uniform_uint{4,7,8}` (l2), `pq` | `num_chunk`, `num_bits`, `opq_iter`, `opq_pq_iter`   |
| `ivf`  | `fp16`, `int8`, `int4`, `pq`                       | the hnsw keys plus `fast_scan`                             |
| `flat` | `fp16`, `int8`, `int4`                             | none                                                       |

- `enums.QUANTIZE_TYPES` grows to the seven tokens. The mapper holds a per-index
  table of allowed quantize types and checks it, plus the metric (uniform) and the
  dtype (PQ), before building anything. That way unit tests cover the rules
  without touching the engine, and errors carry `details.valid`.
- PQ keys are folded into the single `zvec.QuantizerParam(...)` that
  `enable_rotate` already builds. The keys are in `_INDEX_PARAMS` for `hnsw`/`ivf`,
  so typos still return `422` with `unknown`/`valid`. A PQ key without
  `quantize_type: "pq"` is its own `422` instead of being silently ignored, which
  is what Zvec does.
- The server checks numeric ranges itself, because Zvec reports every bad PQ
  value as "Invalid PQ/OPQ parameters; FastScan requires IVF PQ4", and a negative
  `opq_iter` raises `TypeError` in the engine's constructor (a `500` today).

```json
{ "name": "docs", "vectors": [{ "name": "embedding", "dim": 768, "index": "ivf",
  "metric": "l2", "params": { "n_list": 1024, "quantize_type": "pq",
  "num_chunk": 96, "num_bits": 4, "fast_scan": true } }] }
```

HNSW rotation guard (removed by ZS-076 once upstream ships a fix):

```json
{ "error": { "code": "schema_validation_error",
    "message": "enable_rotate is not supported on hnsw indexes with int8 quantization: Zvec 0.8 returns wrong results for this combination after optimize. Use flat or ivf, or omit enable_rotate.",
    "details": { "index": "hnsw", "quantize_type": "int8" } } }
```

### Query params (`adapter/query_mapper.py`)

| Index         | Allowed `queries[].params` (new in bold)                                       |
| ------------- | ------------------------------------------------------------------------------ |
| `hnsw`        | `ef`, `radius`, `is_linear`, `is_using_refiner`, **`scale_factor`**             |
| `hnsw_rabitq` | `ef`, `radius`, `is_linear`, `is_using_refiner`, **`scale_factor`**             |
| `ivf`         | `nprobe`, **`is_using_refiner`**, **`scale_factor`**                            |
| `ivf_rabitq`  | unchanged                                                                      |
| `flat`        | none                                                                           |

- `vector_index_types()` becomes `vector_index_info()` and returns the index type
  plus the quantize type per field, both read from the open collection's schema
  (SPEC-011 R7). The mapper rejects `is_using_refiner: true` on `HNSW` +
  `UNDEFINED`. IVF without quantization refines correctly, so it is allowed there.
- `scale_factor < 0` returns `400`. Zvec fails inside Gandiva, which surfaces as a
  `500` today.
- Engine defaults differ: `scale_factor` 0 on HNSW means max(topk, ef) candidates,
  while IVF defaults to 10. The API docs say so, and the server never injects
  defaults.

### Ids (`api/vectors.py`, models unchanged)

- `GET /collections/{name}/docs/{doc_id:path}` lets `%2F`-encoded or literal `/`
  ids route. No other route shares the `/docs/` GET prefix.
- Field names: Zvec 0.8 allows ASCII names up to 64 bytes (was 32) and rejects
  non-ASCII with a clear message. That already maps to `422`, so only docs change.

### Layers and docs

The API and manager don't change beyond the route converter. Docs: the quantizer
and refiner tables and measured trade-offs in `docs/API.md`, the RaBitQ platform
note in the README and model descriptions, the id rules, and CHANGELOG entries.
The benchmark quant sweep gains the new variants and a refiner dimension
(ZS-074).

## Acceptance criteria

- On 0.8.1, the full suite passes. Collections built with 0.7.0, including
  HNSW + `int8` + rotation, open and keep their recall.
- Each allowed index × new quantizer builds, echoes its `index_param`, and returns
  the exact match first after optimize, using the refiner for `pq`.
- Each disallowed combination (uniform on `ivf`/`flat`/`cosine`, `pq` on `flat`
  or FP16, uniform + rotation, PQ keys without `pq`, out-of-range PQ values,
  `fast_scan` on `hnsw` or with 8 bits, `opq_*` without rotation, `hnsw` + `int8`
  + rotation) returns `422` with a specific message.
- `scale_factor` and `is_using_refiner` work where listed. A refiner on fp32
  `hnsw` and a negative `scale_factor` return `400`.
- Ids with spaces, `/`, `,`, `'`, non-ASCII, and 1,024 bytes insert, fetch, and
  `GET` correctly. 1,025 bytes, newline, and NUL return `400`.
- `docs/API.md` reports SIFT1M numbers for the new quantizers, with and without
  the refiner.

## Risks and open questions

- **Upstream regression.** The HNSW rotation guard is breaking for anyone who
  creates such collections on 0.2.0. Existing ones keep working: we measured a
  0.7.0-built HNSW + `int8` + rotation collection at full recall after reopening
  and re-optimizing under 0.8.1. The guard should be removed as soon as upstream
  fixes the bug (ZS-076), and the bug should be reported upstream.
- **More fields in responses.** `index_param.quantizer_param` now carries six keys
  instead of one. That's additive, but strict client-side schema checks would
  notice.
- **Message matching.** The RaBitQ "not supported on this platform" mapping stays
  for Windows on ARM64 and other platforms without RaBitQ, but CI can no longer
  exercise it.
- **PQ training.** The codebook is learned during `optimize`, and searches before
  that go through Flat. Recall and memory change once the first optimize runs, so
  the API docs should say so.

## Tickets

- ZS-068 — Require Zvec 0.8.1
- ZS-069 — Reject enable_rotate on hnsw scalar quantization (Zvec 0.8 regression)
- ZS-070 — Uniform and PQ quantizers
- ZS-071 — Refiner search params for hnsw, hnsw_rabitq, and ivf
- ZS-072 — Refiner on an unquantized hnsw field returns 500
- ZS-073 — Accept Zvec 0.8 document ids, including in GET /docs/{doc_id}
- ZS-074 — Benchmark the new quantizers and the refiner
- ZS-075 — Document the Zvec 0.8.1 upgrade and measured trade-offs
- ZS-076 — Lift the hnsw rotation guard once Zvec fixes the regression

Bugs found while reviewing this work: ZS-077 (fp16 + rotation, SPEC-011), plus
ZS-078 and ZS-079, which are backlogged and predate this spec.
