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

### Quantization sweep

```bash
# every variant on the engine tier (recall / QPS / disk / optimize time)
uv run python -m benchmarks quant --scenario sift1m
# server-process RSS in isolation, a subset of variants
uv run python -m benchmarks quant --scenario sift1m --tier http --variants fp32,int8,uint8
# also measure every quantized variant with the query-time refiner (scale_factor 0)
uv run python -m benchmarks quant --scenario sift1m --refine 0 --ef 200 --concurrency 16
# PQ on IVF, including 4-bit fast-scan
uv run python -m benchmarks quant --scenario sift1m --index ivf --nprobe 10,50 \
  --variants fp32,pq,pq4,pq4+fs --refine 10
```

Rebuilds the collection once per variant and writes a side-by-side table
(`quant-*.md`, plus the raw `quant-*.json`) with recall, Δrecall vs FP32, QPS,
latency, on-disk size, optimize time, and peak RSS. Variants:

| Variant | Quantizer | Builds on |
| ------- | --------- | --------- |
| `fp32` | none (baseline) | any |
| `fp16`, `int8`, `int4` | scalar | hnsw / flat / ivf |
| `int8+rot`, `int4+rot` | scalar + random rotation | hnsw / flat / ivf (the server rejects these on hnsw — zvec 0.8.x bug, see below) |
| `uint8`, `uint7`, `uint4` | zvec 0.8 uniform (`uniform_uint*`) | hnsw, L2 metric only |
| `pq`, `pq4` | product quantization, 8 / 4 bits per code | hnsw / ivf, `VECTOR_FP32` only |
| `pq+opq` | PQ with learned rotation (OPQ) | hnsw / ivf |
| `pq4+fs` | 4-bit PQ with fast-scan | ivf only |

PQ uses `num_chunk = dim // 4` (32 for SIFT's 128-d) unless `--pq-chunks` says
otherwise. The default `--variants` is everything that builds on HNSW; a variant
the scenario's index/metric cannot build, or that a tier rejects (e.g. the
`http` tier's `422` for `int8+rot` on HNSW), is skipped and listed under
**Skipped** instead of aborting the sweep.

`--refine SF[,SF...]` adds a refined copy of every search cell for quantized
variants: the engine re-scores the quantized candidates against the stored
full-precision vectors (`is_using_refiner` + `scale_factor`; on HNSW `0` means
`max(topk, ef)` candidates, IVF defaults to `10`). FP32 is never refined — it
has nothing to refine, and zvec 0.8.1 raises on an unquantized HNSW field.
`--index`, `--ef`, `--nprobe`, and `--concurrency` override the scenario's
index type and search grid.

SIFT1M, Zvec 0.7.0, HNSW `M=16`, recall@10 at `ef=200` (Apple M-series laptop):

| variant | disk | server RSS (http, mmap) | recall@10 | engine QPS (c=16) |
| --- | ---: | ---: | ---: | ---: |
| fp32 | 688 MB | ~980 MB | 0.996 | 13.0k |
| fp16 | 945 MB | ~1,320 MB | 0.995 | 14.3k |
| int8 | 822 MB | ~1,205 MB | 0.987 | 13.1k |
| int8+rot | 822 MB | — | 0.980 | 12.0k |
| int4 | 762 MB | — | 0.714 | 10.9k |
| int4+rot | 762 MB | — | 0.541 | 12.5k |

Zvec stores the quantized index *in addition to* the full-precision vectors, so
quantization raised disk and memory here instead of lowering them, and rotation
hurt `int4`. Re-run on your own (especially higher-dimensional) data before
enabling it.

SIFT1M, Zvec 0.8.1, same settings (HNSW `M=16`, `ef_construction=200`,
recall@10 at `ef=200`, `--mmap`), Apple M5 (10 cores, 16 GB). "+refine" is the
query-time refiner at `scale_factor=0` (re-score `max(topk, ef)` = 200
candidates). Server RSS is the http tier's peak during ingest + optimize, as a
range over 2–3 runs (it was noisy on this 16 GB laptop under memory pressure):

| variant | disk | server RSS (http) | recall@10 | +refine | engine QPS (c=16) | +refine | optimize |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fp32 | 687 MB | ~860–960 MB | 0.996 | — | 21.3k | — | 47 s |
| fp16 | 946 MB | ~1,310–1,600 MB | 0.996 | 0.996 | 24.1k | 10.8k | 35 s |
| int8 | 823 MB | ~1,310–1,380 MB | 0.987 | 0.995 | 26.7k | 11.0k | 34 s |
| int8+rot | 823 MB | `422` | **0.000** | **0.000** | 28.3k | 11.3k | 31 s |
| int4 | 763 MB | — | 0.867 | 0.996 | 20.2k | 10.9k | 34 s |
| int4+rot | 763 MB | `422` | **0.000** | **0.000** | 26.6k | 11.2k | 31 s |
| uint8 | 823 MB | ~900–1,160 MB | 0.995 | 0.995 | 25.6k | 11.0k | 35 s |
| uint7 | 823 MB | ~1,020–1,150 MB | 0.965 | 0.995 | 25.9k | 10.9k | 34 s |
| uint4 | 763 MB | ~890–1,070 MB | 0.834 | 0.994 | 24.8k | 10.6k | 35 s |
| pq (32×8 bit) | 732 MB | ~970–1,090 MB | 0.717 | 0.991 | 25.5k | 11.0k | 56 s |
| pq4 (32×4 bit) | 701 MB | ~1,350–1,490 MB | 0.400 | 0.922 | 25.2k | 10.3k | 37 s |
| pq+opq | 732 MB | ~1,090–1,110 MB | 0.623 | 0.991 | 24.5k | 11.2k | 66 s |

- Quantization still adds to disk and RSS on 0.8.1; even PQ (32 B/vector)
  is +7% disk, because the FP32 vectors stay alongside.
- Without the refiner, every quantized HNSW variant beats FP32 QPS by 13–25%
  (except `int4`). The refiner at `scale_factor=0` brings recall back to about
  FP32 levels (0.99+, `pq4` 0.92) but cuts c=16 QPS to about 11k, half of FP32.
- A smaller refine window costs almost nothing. For `pq`, `scale_factor=5` (50
  candidates) gave 0.984 recall at 23.7k QPS and `scale_factor=2` gave 0.908 at
  25.0k (`uint8` held 0.996 at any scale factor).
- **HNSW + INT8/INT4 + `enable_rotate` is broken on 0.8.x:** recall@10 is
  0.000 after optimize, refined or not (0.7.0 gave 0.980 / 0.541). The server
  rejects that combination with `422`; the engine tier still builds it, so this
  sweep shows the bug.

### Search latency during optimize

```bash
uv run python -m benchmarks optimize-load --scenario smoke --tier http --concurrency 4
```

Ingests without optimizing, measures a baseline search window, then keeps
searching while `optimize` runs and compares QPS / p50 / p99 / max latency. Use
it to check that optimize does not block reads. Smoke, http tier, c=4, on an
Apple M-series laptop:

| server | queries during optimize | max latency |
| --- | ---: | ---: |
| v0.1.2 (exclusive lock, zvec 0.5.0) | 8 in 2.1 s | 2,112 ms |
| shared-lock optimize (zvec 0.7.0) | 2,609 in 1.5 s | 19 ms |

QPS still drops while optimize runs — that is optimize competing for CPU (the
lock-free `engine` tier shows the same drop), not blocking.

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
| `--quantize <t>` | — | quantize the index: `fp16` \| `int8` \| `int4` \| `uniform_uint8` \| `uniform_uint7` \| `uniform_uint4` \| `pq` |
| `--rotate` | off | random rotation before quantizing (OPQ for `pq`; with `--quantize`) |
| `--num-chunk <n>` / `--num-bits <4\|8>` | engine default | PQ sub-quantizers / bits per code (with `--quantize pq`) |
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
- **mmap.** Zvec **0.5.x** had an mmap forward-store bug: under
  `enable_mmap=True`, a few freshly-optimized docs failed to resolve and came
  back with empty ids (`mmap_forward_store.cc ... Failed to find target chunk`
  on stderr). It is fixed in **0.7.0** (the minimum this server now requires):
  `--mmap` runs are clean and recall matches `--no-mmap`. Benchmarks still
  default to **mmap off**; the production server defaults to mmap on, so use
  `--mmap` to benchmark that configuration.
- **Write batch size.** Zvec caps a single write at 1024 docs, so ingest batches
  are ≤ 1000.
- **IVF tuning.** `nprobe` sweeps apply on every tier (the server honors IVF
  `nprobe`). The shipped scenarios use HNSW.
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
