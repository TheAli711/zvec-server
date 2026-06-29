---
id: ZS-027
title: Engine, in-process, and HTTP runner tiers
spec: SPEC-007
type: feature
priority: P1
status: done
release: v0.1.1
created: 2026-06-25
closed: 2026-06-29
---

# ZS-027: Engine, in-process, and HTTP runner tiers

## Summary

Implement the three SPEC-007 tiers behind one synchronous `Runner` protocol so the
harness (ZS-028) can drive every tier with the same code: **engine** (native `zvec`
only), **inproc** (the server's models, lock, and adapter, no socket), and **http** (a
real `uvicorn` subprocess, called with `httpx` over loopback).

## Acceptance criteria

- [x] `runners/base.py` defines the `Runner` protocol (`setup`, `ingest`, `optimize`,
      `search`, `teardown`, `target_pid`) and
      `SearchOutcome(ids, request_bytes, response_bytes)`.
- [x] `EngineRunner` builds its schema from native `Hnsw`/`IVF`/`FlatIndexParam`,
      with `InvertIndexParam` for indexed scalars. It queries with
      `HnswQueryParam(ef)` or `IVFQueryParam(nprobe)`.
- [x] `InprocRunner` goes through `CollectionManager.create`, the
      `WriteRequest`/`SearchRequest` models, the `ManagedCollection` RW lock, and
      `adapter.operations`.
- [x] `HttpRunner` starts `uvicorn zvec_server.app:create_app --factory --workers 1`
      on a free loopback port. Auth is disabled and it gets its own
      `ZVEC_SERVER_DATA_DIR`. The runner waits up to 30 s for `/readyz` and records
      the request and response bytes of every search.
- [x] Every runner wipes its data dir in `setup` and removes it in `teardown`. The
      http runner also drops the collection and then stops the subprocess: it
      terminates it and kills it if it hasn't exited after 10 s.
- [x] `--query-threads` reaches every tier: through `init_zvec(query_threads=...)`
      in-process, and through `ZVEC_SERVER_ZVEC_QUERY_THREADS` for the subprocess.

## Notes

- The engine runner is the only benchmark code that imports `zvec`. It lives outside
  `zvec_server`, so the adapter-isolation rule does not apply to it.
- After setup, ingest, and optimize, which run single-threaded, `search` must be safe
  to call from many threads at once. `httpx.Client` is thread-safe, so one client can
  be shared.
- `inproc` takes the lock synchronously in the calling thread, the same way handlers
  do inside `run_in_threadpool`.
- Searches over `inproc` and `http` send only `{"ef": ...}`. The server's query mapper
  ignores any other key, so `nprobe` has an effect only on the engine tier.

## Resolution

Added `benchmarks/runners/` with all three tiers. One deviation from the plan: the
http runner writes the server's stdout and stderr to `server.log` instead of an
undrained `PIPE`. Under concurrent load the ~64 KB pipe buffer filled up, blocked the
server's logging write, and deadlocked its event loop. If the server exits early or
never becomes ready, its log is included in the error.
