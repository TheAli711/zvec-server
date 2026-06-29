"""Dataset loading: synthetic (fast), SIFT1M (recall-meaningful), and any
ann-benchmarks-format HDF5 (``train`` / ``test`` / ``neighbors``).

Each loader returns a :class:`Dataset`. Ground truth is taken from the file when
present, otherwise computed and cached via :mod:`benchmarks.groundtruth`. Doc
ids are simply the corpus row index rendered as a string, so the harness can map
search hits back to integers for recall.

Downloads and computed ground truth are cached under ``benchmarks/.datasets``
(git-ignored). Cohere 768d is not auto-downloaded here — point ``--hdf5`` at a
local ann-benchmarks-format file, or use Track B (VectorDBBench) for Cohere.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from benchmarks.groundtruth import cached_ground_truth

__all__ = ["CACHE_DIR", "Dataset", "load_hdf5", "sift1m", "synthetic"]

CACHE_DIR = Path(__file__).resolve().parent / ".datasets"

# ann-benchmarks mirror; sift-128-euclidean ships train/test/neighbors.
_SIFT_URL = "http://ann-benchmarks.com/sift-128-euclidean.hdf5"


@dataclass
class Dataset:
    """A loaded benchmark dataset.

    Attributes:
        name: Human-readable id (used in result filenames).
        train: ``(N, d)`` float32 corpus.
        queries: ``(Q, d)`` float32 query vectors.
        ground_truth: ``(Q, >=k)`` int64 exact neighbour indices.
        metric: ``l2`` | ``ip`` | ``cosine``.
    """

    name: str
    train: np.ndarray
    queries: np.ndarray
    ground_truth: np.ndarray
    metric: str

    @property
    def dim(self) -> int:
        return int(self.train.shape[1])

    @property
    def n(self) -> int:
        return int(self.train.shape[0])

    def doc_ids(self) -> list[str]:
        return [str(i) for i in range(self.n)]


def synthetic(
    n: int = 10_000,
    dim: int = 64,
    n_queries: int = 200,
    metric: str = "l2",
    k: int = 100,
    seed: int = 1234,
) -> Dataset:
    """Random unit-ish vectors with brute-force ground truth. Seconds to build."""
    rng = np.random.default_rng(seed)
    train = rng.standard_normal((n, dim), dtype=np.float32)
    queries = rng.standard_normal((n_queries, dim), dtype=np.float32)
    gt = cached_ground_truth(train, queries, k, metric, CACHE_DIR)
    return Dataset(f"synthetic-{n}x{dim}", train, queries, gt, metric)


def load_hdf5(path: str | Path, metric: str, k: int = 100) -> Dataset:
    """Load an ann-benchmarks-format HDF5 file (``train``/``test``/``neighbors``)."""
    import h5py

    path = Path(path)
    with h5py.File(path, "r") as f:
        train = np.asarray(f["train"], dtype=np.float32)
        queries = np.asarray(f["test"], dtype=np.float32)
        gt = np.asarray(f["neighbors"], dtype=np.int64) if "neighbors" in f else None
    if gt is None:
        gt = cached_ground_truth(train, queries, k, metric, CACHE_DIR)
    return Dataset(path.stem, train, queries, gt, metric)


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    return dest


def sift1m(k: int = 100) -> Dataset:
    """SIFT1M (128-dim, 1M, L2) from the ann-benchmarks mirror. ~500 MB download."""
    dest = _download(_SIFT_URL, CACHE_DIR / "sift-128-euclidean.hdf5")
    return load_hdf5(dest, metric="l2", k=k)
