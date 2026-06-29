# Zvec Server benchmarks

Benchmarks for [Zvec Server](../README.md). The headline question this suite
answers is one that the upstream [zvec.org
benchmarks](https://zvec.org/en/docs/db/benchmarks/) cannot: **how much does the
HTTP server add on top of the raw Zvec engine, and where does that cost go —
server logic or the network/JSON boundary?**

There are two tracks:

- **Track A — overhead decomposition** (this package). The *same* workload runs
  through three tiers, so the cost of each layer can be measured in isolation.
- **Track B — zvec.org parity** ([`vdbbench/`](./vdbbench)). A
  [VectorDBBench](https://github.com/zilliztech/VectorDBBench) client plugin that
  points the community-standard harness at the REST API, for numbers directly
  comparable to zvec.org. VectorDBBench is a heavy, **manual** install — see its
  [README](./vdbbench/README.md).

## The three tiers (Track A)

| Tier | What runs | Isolates |
| ---- | --------- | -------- |
| `engine` | `zvec` SDK called directly in-process (native `Doc`/`Query`) | the **floor** — what zvec.org measures |
| `inproc` | build the Pydantic request → `ManagedCollection` RW lock → `adapter.operations.*` → response model (no socket) | the **server-logic tax**: validation + mappers + lock + threadpool |
| `http`   | a real `uvicorn` subprocess + `httpx` over loopback TCP, full FastAPI stack | the **transport tax**: ASGI + JSON encode/decode + TCP |

So **server-logic tax = inproc − engine** and **transport tax = http − inproc**.
The same vectors, queries and parameters drive every tier, and concurrency is
closed-loop (`N` worker threads issuing as fast as possible, matching
VectorDBBench's `--num-concurrency`).

## Install & run

```bash
uv sync --extra bench

# fast synthetic smoke run across all three tiers (seconds)
uv run python -m benchmarks run --scenario smoke

# list scenarios
uv run python -m benchmarks list
```

Results land in `benchmarks/results/<scenario>-<timestamp>.json` (git-ignored),
a `report.md` with tables, and `report.md`'s plots under `results/plots/`. A
compact summary plus the **overhead-decomposition** table are printed to stdout.

### Flags

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--scenario` | `smoke` | `smoke` \| `sift1m` \| `cohere1m` \| `cohere10m` |
| `--tiers` | `engine,inproc,http` | comma-separated subset to run |
| `--hdf5 <path>` | — | ann-benchmarks-format file (required by the `cohere*` scenarios) |
| `--measure-seconds <s>` | per-scenario | override the per-cell measurement window |
| `--query-threads <n>` | engine default | set `ZVEC_SERVER_ZVEC_QUERY_THREADS` for all tiers |
| `--mmap` / `--no-mmap` | `--no-mmap` | memory-mapped storage (see the mmap note below) |
| `--out <dir>` | `benchmarks/results` | results directory |

## Scenarios

| Scenario | Dataset | Dim × N | Notes |
| -------- | ------- | ------- | ----- |
| `smoke`     | synthetic | 64 × 10k | seconds; the quick check |
| `sift1m`    | SIFT1M (auto-downloaded from the ann-benchmarks mirror) | 128 × 1M | `ef` sweep for the QPS–recall curve; ships ground truth |
| `cohere1m`  | your local Cohere HDF5 (`--hdf5`) | 768 × 1M | params per zvec.org: `M=15`, `ef=180` |
| `cohere10m` | your local Cohere HDF5 (`--hdf5`) | 768 × 10M | params per zvec.org: `M=50`, `ef=118` |

Cohere is not auto-downloaded; pass an ann-benchmarks-format HDF5
(`train`/`test`/`neighbors`) via `--hdf5`, or use Track B for Cohere.

## Reading the results

The headline is the **overhead-decomposition** table: for each shared grid cell
(topk, ef, concurrency, filter) it shows engine/inproc/http p50 latency and QPS
side by side, plus `Δ_logic` and `Δ_transport`. The plots include a QPS–recall
curve (the `ef` sweep), QPS vs concurrency, a latency-percentile curve per tier,
and a stacked latency breakdown (engine | logic | transport).

For vector search the transport tax is dominated by **JSON encoding of the
vectors**: a 768-dim fp32 vector is ~3 KB raw but ~15–20 KB as a JSON number
array. The `http` tier records the average request/response bytes per search so
this shows up directly.

## Methodology & caveats

- **Single worker.** The server is single-process by design. Reads share the
  per-collection lock and scale until the threadpool / `ZVEC_SERVER_ZVEC_QUERY_THREADS`
  saturates; **writes are exclusive**, so write throughput does not scale with
  concurrency on one collection. The grids exercise read concurrency.
- **Recall.** Every search cell reports recall@k against exact neighbours
  (brute-force, cached under `benchmarks/.datasets`, or the dataset's bundled
  ground truth). A Zvec `flat` index reproduces these exactly (recall ≈ 1.0),
  which doubles as an engine sanity check.
- **Loopback.** The `http` tier runs the client and server on the same host, so
  there is no NIC variance — but real TCP + JSON is still exercised. For true
  round-trip latency, run a client against a server on a second host.
- **Memory (RSS).** For `http` the sampled RSS is the server subprocess only — a
  clean engine-memory figure. For `engine`/`inproc` it is the whole benchmark
  process (it also holds the dataset in NumPy), so compare RSS *across runs of
  the same tier*, not across tiers.
- **mmap quirk.** Zvec **0.5.0** has an mmap forward-store bug: under
  `enable_mmap=True`, a few freshly-optimized docs fail to resolve and come back
  with empty ids (you'll see `mmap_forward_store.cc ... Failed to find target
  chunk` on stderr). Benchmarks therefore default to **mmap off** for clean,
  trustworthy recall. The production server defaults to mmap on — benchmark that
  configuration with `--mmap` (the harness tolerates the empty ids; recall will
  dip slightly for the affected queries).
- **Write batch size.** Zvec caps a single write at 1024 docs, so ingest batches
  are ≤ 1000.
- **IVF tuning.** The server's query mapper only tunes HNSW `ef` today, so IVF
  `nprobe` sweeps take effect on the `engine` tier only. The shipped scenarios
  use HNSW.
- **Reproducibility.** Each result JSON captures CPU/RAM/OS, Python + Zvec
  versions, the git commit, and the thread/mmap config.

## Layout

```
benchmarks/
  cli.py            # python -m benchmarks run ...
  scenarios.py      # dataset + spec + search grid bundles
  datasets.py       # synthetic / SIFT1M / HDF5 loaders (+ ground truth)
  groundtruth.py    # exact neighbours via brute force, cached
  harness.py        # ingest, warmup, closed-loop concurrency, recall
  metrics.py        # recall@k, latency percentiles, RSS sampling
  results.py        # the result JSON schema (+ env capture)
  report.py         # results JSON -> report.md + plots
  spec.py           # CollectionSpec (engine-agnostic)
  runners/
    base.py         # the Runner protocol + SearchOutcome
    engine.py       # Tier 1
    inproc.py       # Tier 2
    http.py         # Tier 3
  vdbbench/         # Track B (manual VectorDBBench install)
```
