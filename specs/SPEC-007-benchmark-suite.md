---
id: SPEC-007
title: Benchmark suite with overhead decomposition
status: implemented
created: 2026-06-25
release: v0.1.1
---

# SPEC-007: Benchmark suite with overhead decomposition

## Summary

Add a benchmark suite under `benchmarks/`. It answers a question the zvec.org
benchmarks cannot: how much does Zvec Server add on top of the raw engine, and is that
cost in the server's own logic or at the HTTP/JSON boundary? The same workload runs
through three tiers: the native engine, the server's request path in-process, and the
real server over loopback. Each tier reports recall, latency percentiles, throughput,
memory, and payload sizes, and the suite reports the deltas between tiers. A second
track plugs the REST API into VectorDBBench so results can be compared with zvec.org.
The suite is a separate, optional package; the server itself does not change.

## Motivation

v0.1.0 (SPEC-001 to SPEC-006) exists to let people use Zvec over HTTP instead of
in-process, so they need to know what that costs. Today we can only point at zvec.org,
whose numbers measure the library in-process. Those numbers say nothing about two
costs:

- The **server-logic tax**: Pydantic validation, the REST⇄Zvec mappers, the
  per-collection RW lock, and threadpool offload (SPEC-002 to SPEC-004).
- The **transport tax**: ASGI, TCP, and above all JSON-encoded float vectors. A
  768-dim fp32 query is about 3 KB raw; we expect it to be 15–20 KB as JSON.

Without a reproducible measurement, regressions in the mappers or the lock go
unnoticed. A single end-to-end number is not enough either. If HTTP is 2x the engine,
we need to know which layer to fix.

## Goals

- Split overhead into `Δ_logic = inproc − engine` and `Δ_transport = http − inproc`,
  measured per grid cell (topk, ef, concurrency, filter).
- Never report speed without quality: every configuration gets recall@k against exact
  neighbours.
- Provide a `smoke` scenario that runs in seconds, plus SIFT1M and Cohere 1M/10M
  scenarios for publishable numbers.
- Write JSON results plus a markdown report with plots.
- Provide a VectorDBBench client so we can compare against zvec.org's Cohere results.

## Non-goals

- Optimizing the server. This spec only measures.
- Concurrent write throughput. Writes are exclusive per collection by design
  (SPEC-002), so ingest is timed single-threaded.
- Multi-host latency, comparisons with other databases, or gating CI on performance.
- Auto-downloading Cohere. SIFT1M is the only dataset fetched automatically.
- Declaring VectorDBBench as a dependency. It is heavy (Streamlit, many DB drivers)
  and is installed by hand in its own virtualenv.

## Requirements

- **R1.** The suite must run an identical workload through three tiers: `engine` (the
  `zvec` SDK directly), `inproc` (the server's Pydantic models, `ManagedCollection`
  lock, and `adapter.operations`, no socket), and `http` (a single-worker `uvicorn`
  subprocess driven by `httpx` over loopback).
- **R2.** The collection shape must be described once, in the server's vocabulary
  (`VECTOR_FP32`, `hnsw|flat|ivf`, `cosine|ip|l2`, `m`, `ef_construction`, `n_list`,
  `n_iters`). Each tier translates that description itself.
- **R3.** Recall@k must be measured against exact neighbours. Use the dataset's
  `neighbors` when it has them; otherwise compute them by brute force in NumPy and
  cache them on disk.
- **R4.** Each search cell must report QPS, recall@k, latency (count, mean, and
  p50/p90/p95/p99/max in ms), and peak RSS. The `http` tier must also report average
  request and response bytes. Ingest must report docs/s, seconds, optimize seconds,
  and peak RSS.
- **R5.** Concurrency must be closed-loop: `N` threads search back to back for a fixed
  window, as with VectorDBBench's `--num-concurrency`. Warmup queries must be
  discarded. Recall must be computed once per (topk, ef, nprobe, filter,
  include_vector) and reused.
- **R6.** The scenarios `smoke`, `sift1m`, `cohere1m`, and `cohere10m` must each bundle
  a dataset, a spec, and a search grid. Cohere scenarios must fail fast when `--hdf5`
  is missing.
- **R7.** Each run must write a JSON result recording host, CPU, RAM, OS, Python and
  Zvec versions, git commit, and thread/mmap settings; a markdown report with plots;
  and a stdout summary including the decomposition table.
- **R8.** Track B must provide a VectorDBBench client (`VectorDB` / `DBConfig` /
  `DBCaseConfig`) over REST. The module must import even when `vectordb_bench` is not
  installed, and the client must map filtered cases onto the server's filter grammar.
- **R9.** The suite must be purely additive: nothing under `zvec_server` imports it,
  its dependencies live in an optional `bench` extra, CI passes without that extra,
  and `mypy` stays scoped to `zvec_server`.
- **R10.** Runs must be hermetic. Each tier gets a fresh temp data directory that is
  removed afterwards. Downloads, cached ground truth, and results are git-ignored.

## Design

### Layout

`benchmarks/` holds `cli.py`/`__main__.py`, `spec.py`, `datasets.py`,
`groundtruth.py`, `scenarios.py`, `harness.py`, `metrics.py`, `results.py`,
`report.py`, `runners/{base,engine,inproc,http}.py`, and `vdbbench/` (Track B). Unit
tests live in `tests/benchmarks/` behind `pytest.importorskip("numpy")`. The `engine`
runner imports `zvec` directly, which does not breach adapter isolation: that rule
governs `zvec_server.*`, and `benchmarks/` only reuses `adapter.runtime.init_zvec`.

### Tiers and the runner contract

| Tier | Path exercised | Isolates |
| --- | --- | --- |
| `engine` | `zvec.create_and_open`, `Collection.insert/query/optimize` | the floor |
| `inproc` | request models → RW lock → `adapter.operations` → response | logic tax |
| `http` | `uvicorn zvec_server.app:create_app --factory --workers 1` + httpx | transport tax |

All tiers implement one synchronous `Runner` protocol: `setup(spec)`,
`ingest(ids, vectors, fields)`, `optimize()` (flush + optimize),
`search(vector, topk, *, ef, nprobe, filter, include_vector) -> SearchOutcome`,
`teardown()`, and `target_pid()` (whose RSS to sample). `SearchOutcome` carries hit ids
plus `request_bytes`/`response_bytes` (http only); doc ids are corpus row indices as
strings. `http` starts the server on a free loopback port with
`ZVEC_SERVER_AUTH_ENABLED=false` and a private `ZVEC_SERVER_DATA_DIR`, waits up to 30 s
for `GET /readyz`, then uses only the public API (`POST /collections`,
`.../docs/insert`, `.../flush`, `.../optimize`, `.../search`, `DELETE`). `inproc` takes
the RW lock synchronously in the worker thread, as handlers do in `run_in_threadpool`.

### Harness

Per tier: `setup` → ingest in batches of 1000 (Zvec caps a write at 1024 docs) →
`optimize` → per grid point, a sequential recall pass over up to 1000 queries (cached
per recall key), warmup, then `N` threads until the window closes → `teardown` in a
`finally`. QPS is completed queries over the wall-clock window. `RssSampler` polls
`psutil` every 100 ms: the server subprocess for `http`, the benchmark process for the
in-process tiers.

### Scenarios

| Scenario | Dataset | dim × N, metric | hnsw build | ef; concurrency | Window |
| --- | --- | --- | --- | --- | --- |
| `smoke` | synthetic, seeded | 64 × 10k, l2 | m=16, efc=200 | {32,128}; {1,8} | 2 s |
| `sift1m` | ann-benchmarks | 128 × 1M, l2 | m=16, efc=200 | {40,80,120,200}; {1,8,16} | 5 s |
| `cohere1m` | local HDF5 | 768 × 1M, cosine | m=15, efc=200 | {180}; {12,16,20} | 8 s |
| `cohere10m` | local HDF5 | 768 × 10M, cosine | m=50, efc=200 | {118}; {12,16,20} | 8 s |

All scenarios use topk 10 and recall@10, with ground truth to k=100. The Cohere
parameters follow zvec.org. The grid also has filter and `include_vector` axes, but
the shipped scenarios run unfiltered. Every scenario uses HNSW because the server's
query mapper only understands `{"ef": int}`. An IVF `nprobe` sweep would therefore
reach only the `engine` tier.

### CLI, results, and report

Install with `uv sync --extra bench`. Then run
`uv run python -m benchmarks run --scenario smoke`, or use `list` to see the
scenarios.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--scenario` | `smoke` | Scenario to run |
| `--tiers` | `engine,inproc,http` | Tiers to run |
| `--hdf5` | none | ann-benchmarks file with `train`, `test`, and `neighbors` |
| `--measure-seconds` | per scenario | Window for each cell |
| `--query-threads` | engine default | Zvec query threads for every tier |
| `--mmap` / `--no-mmap` | off | Storage mode for the collection under test |
| `--out` | `benchmarks/results` | Output directory |

`<scenario>-<timestamp>.json` holds `scenario`, `dataset`, `spec` (+ `recall_k`),
`env`, and `tiers[]`; each tier has `ingest` (`n_docs`, `batch_size`, `seconds`,
`docs_per_sec`, `optimize_seconds`, `peak_rss_mb`) and `searches[]` (`concurrency`,
`topk`, `ef`, `nprobe`, `filter`, `qps`, `recall_at_k`, `latency{count, mean_ms,
p50_ms…max_ms}`, `measured_queries`, `peak_rss_mb`, `avg_request_bytes`,
`avg_response_bytes`). `report.md`, written next to it, has Environment, Ingest, Search
(per tier), Overhead decomposition (per-tier p50/QPS, `Δ_logic_ms`, `Δ_transport_ms`),
Payload (average request vs raw `dim × 4` bytes), and Plots under `plots/`: QPS vs
recall, QPS vs concurrency, latency percentiles, and a stacked engine/logic/transport
breakdown. `python -m benchmarks.report <result.json> [out_dir]` re-renders it.

### Track B and packaging

`benchmarks/vdbbench/zvec_rest_client.py` defines `ZvecRest(VectorDB)`,
`ZvecRestConfig(DBConfig)` (`host`, `port`, `timeout`), and
`ZvecRestHNSWConfig(DBCaseConfig)` (`metric_type`, `M`, `efConstruction`, `ef`). The
client creates an `hnsw` `VECTOR_FP32` collection with an indexed `INT64` `id`
field and mirrors each doc's integer id into that field. A `filters={"id": X}` case
becomes `id >= X`. VectorDBBench has no plugin discovery, so the README shows how to
register the classes on a `TaskConfig` at runtime. The import is guarded:
constructing the client without the package raises a clear `ImportError`.

`pyproject.toml` gains `bench = ["numpy>=2.0", "httpx>=0.27", "psutil>=6.0",
"h5py>=3.11", "matplotlib>=3.9"]` and pytest `pythonpath = ["."]`.

## Acceptance criteria

- `run --scenario smoke` runs all three tiers with no download. It prints per-tier
  summaries and the decomposition table.
- A run writes a result JSON, `report.md`, and PNG plots. The report can be rebuilt
  from the JSON alone.
- On `smoke`, all three tiers report recall within noise of each other for the same
  cell.
- Ground truth matches hand-computed neighbours for `l2`, `ip`, and `cosine`. Batch
  size does not change it, and a repeat call reads it from the cache.
- `cohere1m` without `--hdf5`, and any unknown scenario name, fail with a clear
  `ValueError`.
- CI passes without the extra: ruff covers `benchmarks/`, the benchmark tests skip,
  and mypy stays scoped to `zvec_server`.
- The VectorDBBench client module imports when `vectordb_bench` is absent.

## Risks and open questions

- For `engine` and `inproc`, RSS includes the dataset held in NumPy, so RSS is only
  comparable within one tier. We will document this rather than fix it.
- Loopback hides NIC latency, so `Δ_transport` is a lower bound.
- Zvec initialises once per process, so `engine` and `inproc` share an engine config.
  `http` must receive the same thread count through `ZVEC_SERVER_ZVEC_QUERY_THREADS`.
- Production defaults to mmap on (SPEC-002), but the suite defaults to off. Production
  numbers need `--mmap`.
- zvec.org may use engine settings the REST schema does not expose. Track B shares
  their harness and recall definition, but not necessarily their absolute QPS or
  memory.
- VectorDBBench's client API differs between `v0.0.20` and `main`. The client must
  accept both.

## Tickets

- ZS-026 — Benchmark specs, datasets, and brute-force ground truth
- ZS-027 — Engine, in-process, and HTTP runner tiers
- ZS-028 — Benchmark harness and metrics: recall@k, latency, QPS, RSS
- ZS-029 — Benchmark CLI, scenarios, and reports
- ZS-030 — VectorDBBench REST adapter
