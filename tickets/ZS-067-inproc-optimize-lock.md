---
id: ZS-067
title: Inproc benchmark runner does not mirror the server's shared-lock optimize
spec: SPEC-014
type: bug
priority: P2
status: done
release: v0.2.0
created: 2026-09-19
closed: 2026-09-19
---

# ZS-067: Inproc benchmark runner does not mirror the server's shared-lock optimize

## Summary

The `inproc` tier exists to run exactly the locking the server runs, minus HTTP.
Since SPEC-010 (ZS-043) the server optimizes through `ManagedCollection.maintain()`:
the shared lock plus the per-collection maintenance mutex, so searches continue.
`InprocRunner.optimize()` still takes the **exclusive** lock for both flush and
optimize. On the `inproc` tier, `optimize-load` (ZS-060) therefore reports reads
blocked by optimize, contradicting the `http` tier and violating SPEC-014 R8.

## Reproduction

1. Run `uv run python -m benchmarks optimize-load --scenario smoke --tier inproc`
   (the subcommand in progress under ZS-060), or start a few threads calling
   `InprocRunner.search()` in a loop and call `InprocRunner.optimize()` on an
   unoptimized collection.
2. Compare with the same run on `--tier http`.

Observed: on `inproc`, searches (which take `rwlock.gen_rlock()`) wait on the
`gen_wlock()` held across `zcol.optimize_collection()`, so almost no queries
complete during optimize and max latency tracks the optimize duration. On `http` the
server's shared-lock optimize lets searches continue.

Expected: both tiers show the server's behaviour; `inproc` differs from `http` only
by transport cost.

## Acceptance criteria

- [x] `InprocRunner.optimize()` flushes under the exclusive lock, as the server's
      `flush` route does.
- [x] It then optimizes under `maintenance_lock` plus the shared lock, matching
      `ManagedCollection.maintain()`.
- [x] Searches on the `inproc` tier keep completing while optimize runs.

## Notes

- Module: `benchmarks/runners/inproc.py`. The runner takes locks synchronously on
  its own threads, so it can't call the async `maintain()` directly; mirror its lock
  usage instead and say so in a comment.
- Only matters when searches overlap an optimize, i.e. `optimize-load` on the
  `inproc` tier; `run` and `quant` optimize before measuring searches, and the
  `engine` and `http` tiers are unaffected.
- Not covered by CI (the benchmark suite is lint-only there).

## Resolution

Split `InprocRunner.optimize()` into a flush under `gen_wlock()` followed by
`zcol.optimize_collection()` under `maintenance_lock` and `gen_rlock()`, with a
comment pointing at `ManagedCollection.maintain`. The fix landed before the
`optimize-load` subcommand (ZS-060), so no published result was affected.
