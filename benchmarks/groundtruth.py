"""Exact nearest-neighbour ground truth via brute force (numpy), with caching.

Recall is only meaningful against exact neighbours, so for any dataset that does
not ship them we compute them once and cache to ``.npy``. The computation is
engine-independent, which also makes it a check on the engine: a ``flat`` index
must reproduce these results (recall ≈ 1.0).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

__all__ = ["cached_ground_truth", "compute_ground_truth"]


def _normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return x / norms


def compute_ground_truth(
    train: np.ndarray,
    queries: np.ndarray,
    k: int,
    metric: str,
    query_batch: int = 256,
) -> np.ndarray:
    """Return the exact top-``k`` neighbour indices for each query.

    Args:
        train: ``(N, d)`` corpus.
        queries: ``(Q, d)`` queries.
        k: Number of neighbours.
        metric: ``l2`` | ``ip`` | ``cosine``.
        query_batch: Queries processed per matmul (bounds peak memory).

    Returns:
        ``(Q, k)`` int64 array of neighbour indices, best-first.
    """
    metric = metric.lower()
    train = train.astype(np.float32, copy=False)
    queries = queries.astype(np.float32, copy=False)
    if metric == "cosine":
        train = _normalize(train)
        queries = _normalize(queries)

    n_q = queries.shape[0]
    out = np.empty((n_q, k), dtype=np.int64)
    train_sq = np.einsum("ij,ij->i", train, train) if metric == "l2" else None

    for start in range(0, n_q, query_batch):
        q = queries[start : start + query_batch]
        if metric == "l2":
            # ||t||^2 - 2 q·t  (drop the constant ||q||^2: rank-preserving)
            scores = train_sq - 2.0 * (q @ train.T)  # smaller = nearer
            idx = np.argpartition(scores, k - 1, axis=1)[:, :k]
            order = np.argsort(np.take_along_axis(scores, idx, axis=1), axis=1)
        else:  # ip / cosine: larger dot = nearer
            scores = q @ train.T
            idx = np.argpartition(-scores, k - 1, axis=1)[:, :k]
            order = np.argsort(-np.take_along_axis(scores, idx, axis=1), axis=1)
        out[start : start + q.shape[0]] = np.take_along_axis(idx, order, axis=1)
    return out


def _fingerprint(train: np.ndarray, queries: np.ndarray, k: int, metric: str) -> str:
    h = hashlib.sha1()
    for a in (train, queries):
        h.update(str(a.shape).encode())
        # Sample a few rows so the hash is cheap but collision-resistant enough.
        h.update(np.ascontiguousarray(a[:: max(1, a.shape[0] // 64)]).tobytes())
    h.update(f"{k}:{metric}".encode())
    return h.hexdigest()[:16]


def cached_ground_truth(
    train: np.ndarray,
    queries: np.ndarray,
    k: int,
    metric: str,
    cache_dir: Path,
) -> np.ndarray:
    """Like :func:`compute_ground_truth` but memoized on disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    fp = _fingerprint(train, queries, k, metric)
    path = cache_dir / f"gt-{fp}.npy"
    if path.exists():
        return np.load(path)
    gt = compute_ground_truth(train, queries, k, metric)
    np.save(path, gt)
    return gt
