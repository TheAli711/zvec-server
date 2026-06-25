---
id: ZS-028
title: Benchmark harness and metrics: recall@k, latency, QPS, RSS
spec: SPEC-007
type: feature
priority: P1
status: todo
release: v0.1.1
created: 2026-06-25
---

# ZS-028: Benchmark harness and metrics: recall@k, latency, QPS, RSS

## Summary

Write the SPEC-007 measurement driver. It has three parts: a harness that works the
same for every tier and drives ingest, optimize, and the search grid through the
`Runner` protocol (ZS-027); pure metric helpers; and the result schema that the CLI
and report (ZS-029) consume. Each tier must be measured identically. Otherwise the
deltas between tiers mean nothing.

## Acceptance criteria

- [ ] `measure_ingest` loads the corpus in `ingest_batch` chunks and then optimizes.
      It times both phases and samples peak RSS.
- [ ] `measure_search` computes recall@k once per (topk, ef, nprobe, filter,
      include_vector), using up to 1000 queries. It then runs the warmup and a
      closed-loop window with `concurrency` threads. QPS is completed queries
      divided by the wall-clock window.
- [ ] `metrics.py` provides `recall_at_k` and `summarize_latencies` (count, mean, and
      p50/p90/p95/p99/max, in ms). Its `RssSampler` polls psutil every 100 ms in a
      background thread and does nothing when no PID is given.
- [ ] `results.py` defines `RunResult`, `TierResult`, `IngestResult`, `SearchResult`,
      and `EnvInfo`. `capture_env()` records the host, platform, CPU, RAM, Python and
      Zvec versions, git commit, query threads, and mmap setting.
- [ ] `run_tier` calls `teardown` even when a phase raises.
- [ ] Unit tests cover recall (partial, perfect, truncated k, empty input), the
      latency percentiles, and the sampler with no PID.

## Notes

- Metrics must not touch Zvec or the network, so they can be unit-tested in
  isolation.
- Recall passes are sequential and run outside the timed window. That keeps the
  throughput passes pure timing, and recall does not depend on concurrency anyway.
- Environment capture must degrade gracefully. If psutil is missing, the hardware
  fields become `None`; if zvec is missing, its version becomes `"unavailable"`.
- Warmup runs on the calling thread before the pool starts. Inside the window, each
  thread sends its next query as soon as the previous one returns.
