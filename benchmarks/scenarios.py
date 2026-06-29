"""Named scenarios: dataset + collection spec + search grid, in tiers.

* ``smoke``    -- synthetic 10k x 64d; seconds; the default for a quick check / CI.
* ``sift1m``   -- SIFT1M 128d x 1M with an ``ef`` sweep for the QPS-recall curve.
* ``cohere1m`` / ``cohere10m`` — 768d, params matching zvec.org; require a local
  ann-benchmarks-format file via ``--hdf5`` (Cohere is not auto-downloaded).

Datasets are loaded lazily (``load`` callable) so listing scenarios is cheap.

Note on IVF: the server's query mapper only tunes HNSW ``ef`` today, so
``nprobe`` sweeps take effect on the **engine** tier only; over inproc/http the
engine uses its default. Scenarios here therefore use HNSW.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from itertools import product

from benchmarks import datasets
from benchmarks.datasets import Dataset
from benchmarks.spec import CollectionSpec

__all__ = ["SCENARIO_NAMES", "Scenario", "SearchGrid", "SearchPoint", "build_scenario"]


@dataclass(frozen=True)
class SearchPoint:
    """One fully-resolved cell of the search grid."""

    topk: int
    ef: int | None
    nprobe: int | None
    concurrency: int
    filter: str | None
    include_vector: bool


@dataclass(frozen=True)
class SearchGrid:
    """Axes of the search sweep; the harness runs the cartesian product."""

    topk: tuple[int, ...] = (10,)
    ef: tuple[int | None, ...] = (None,)
    nprobe: tuple[int | None, ...] = (None,)
    concurrency: tuple[int, ...] = (1,)
    filters: tuple[str | None, ...] = (None,)
    include_vector: tuple[bool, ...] = (False,)

    def points(self) -> list[SearchPoint]:
        return [
            SearchPoint(tk, ef, np, c, flt, iv)
            for tk, ef, np, c, flt, iv in product(
                self.topk,
                self.ef,
                self.nprobe,
                self.concurrency,
                self.filters,
                self.include_vector,
            )
        ]


@dataclass(frozen=True)
class Scenario:
    """A complete benchmark definition."""

    name: str
    load: Callable[[], Dataset]
    spec: CollectionSpec
    grid: SearchGrid
    recall_k: int = 10
    ingest_batch: int = 1_000
    warmup_queries: int = 50
    measure_seconds: float = 3.0
    repetitions: int = 1
    extra: dict[str, object] = field(default_factory=dict)


def _smoke() -> Scenario:
    return Scenario(
        name="smoke",
        load=partial(datasets.synthetic, n=10_000, dim=64, n_queries=200, metric="l2", k=100),
        spec=CollectionSpec(
            name="bench_smoke", dim=64, index="hnsw", metric="l2", m=16, ef_construction=200
        ),
        grid=SearchGrid(topk=(10,), ef=(32, 128), concurrency=(1, 8)),
        recall_k=10,
        ingest_batch=1_000,
        warmup_queries=50,
        measure_seconds=2.0,
    )


def _sift1m() -> Scenario:
    return Scenario(
        name="sift1m",
        load=partial(datasets.sift1m, k=100),
        spec=CollectionSpec(
            name="bench_sift1m", dim=128, index="hnsw", metric="l2", m=16, ef_construction=200
        ),
        grid=SearchGrid(topk=(10,), ef=(40, 80, 120, 200), concurrency=(1, 8, 16)),
        recall_k=10,
        ingest_batch=1_000,
        warmup_queries=200,
        measure_seconds=5.0,
    )


def _cohere(name: str, hdf5: str, m: int, ef_search: int) -> Scenario:
    return Scenario(
        name=name,
        load=partial(datasets.load_hdf5, hdf5, metric="cosine", k=100),
        spec=CollectionSpec(
            name=f"bench_{name}", dim=768, index="hnsw", metric="cosine", m=m, ef_construction=200
        ),
        grid=SearchGrid(topk=(10,), ef=(ef_search,), concurrency=(12, 16, 20)),
        recall_k=10,
        ingest_batch=1_000,
        warmup_queries=200,
        measure_seconds=8.0,
    )


SCENARIO_NAMES = ("smoke", "sift1m", "cohere1m", "cohere10m")


def build_scenario(name: str, hdf5: str | None = None) -> Scenario:
    """Resolve a scenario by name. Cohere variants need ``hdf5``."""
    if name == "smoke":
        return _smoke()
    if name == "sift1m":
        return _sift1m()
    if name in ("cohere1m", "cohere10m"):
        if not hdf5:
            raise ValueError(f"scenario {name!r} requires --hdf5 <ann-benchmarks file>")
        # zvec.org headline params: 1M -> M=15 ef=180; 10M -> M=50 ef=118.
        m, ef = (15, 180) if name == "cohere1m" else (50, 118)
        return _cohere(name, hdf5, m=m, ef_search=ef)
    raise ValueError(f"unknown scenario {name!r}; choose from {SCENARIO_NAMES}")
