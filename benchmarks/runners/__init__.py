"""Tier runners: the same workload through different amounts of the stack.

* :mod:`benchmarks.runners.engine` — Tier 1, native ``zvec`` in-process (the floor).
* :mod:`benchmarks.runners.inproc` — Tier 2, the server's adapter + manager + RW
  lock, no HTTP.
* :mod:`benchmarks.runners.http` — Tier 3, a real uvicorn process over loopback.

All runners implement the synchronous :class:`benchmarks.runners.base.Runner`
protocol so the harness can drive any tier with one concurrency model.
"""

from __future__ import annotations

__all__ = ["base", "engine", "http", "inproc"]
