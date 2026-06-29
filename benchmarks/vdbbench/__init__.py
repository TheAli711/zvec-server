"""Track B — VectorDBBench parity for Zvec Server.

This package is a *client plugin* for `VectorDBBench
<https://github.com/zilliztech/VectorDBBench>`_ (PyPI: ``vectordb-bench``,
import package ``vectordb_bench``). It lets the community-standard harness drive
Zvec Server over its REST API so the QPS / recall / build-time numbers come out
directly comparable to the ones published on zvec.org (which runs VectorDBBench
on Cohere 1M / 10M).

VectorDBBench is a heavy, intentionally-manual dependency: it is **not** a
declared dependency of this project. Install it yourself (ideally in its own
virtualenv) before using this plugin -- see ``README.md`` in this directory.

The actual adapter lives in :mod:`benchmarks.vdbbench.zvec_rest_client`. Importing
that module does **not** require ``vectordb_bench`` to be installed (the import is
guarded); the dependency is only needed to actually *run* a case.

Nothing here is imported by the server, and this ``__init__`` deliberately
performs no heavy imports.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
