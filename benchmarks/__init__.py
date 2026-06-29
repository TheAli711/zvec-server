"""Benchmarking suite for Zvec Server.

Two tracks:

* **Track A — overhead decomposition.** The same workload is run through three
  tiers (``engine`` → ``inproc`` → ``http``) so the cost of the server's logic
  and of the HTTP/JSON boundary can be measured in isolation. See
  :mod:`benchmarks.runners`.
* **Track B — zvec.org parity.** A VectorDBBench client plugin that points the
  community-standard harness at the REST API. See :mod:`benchmarks.vdbbench`.

Run it with ``uv run python -m benchmarks run --scenario smoke`` after
``uv sync --extra bench``. Nothing here is imported by the server itself.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
