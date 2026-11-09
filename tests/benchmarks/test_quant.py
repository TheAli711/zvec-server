"""Unit tests for the quantization sweep's variant table and report."""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from benchmarks.cli import QUANTIZE_TYPES
from benchmarks.quant import (
    DEFAULT_VARIANTS,
    VARIANTS,
    Variant,
    _table,
    apply_variant,
    skip_reason,
)
from benchmarks.runners.base import server_query_params
from benchmarks.spec import CollectionSpec

from zvec_server.adapter.enums import QUANTIZE_TYPES as SERVER_QUANTIZE_TYPES


def _row(variant: str, recall: float, refine: float | None = None) -> dict[str, object]:
    return {
        "variant": variant,
        "disk_mb": 10.0,
        "optimize_seconds": 1.5,
        "peak_rss_mb": 90.0,
        "searches": [
            {
                "concurrency": 1,
                "ef": 64,
                "nprobe": None,
                "recall_at_k": recall,
                "qps": 1234.0,
                "latency": {"p50_ms": 0.1, "p99_ms": 0.2},
                "refine": refine,
            }
        ],
    }


def test_variants_cover_every_quantize_type() -> None:
    assert VARIANTS["fp32"] == Variant(None)
    assert {v.quantize_type for v in VARIANTS.values()} == {None, *SERVER_QUANTIZE_TYPES}
    assert set(QUANTIZE_TYPES) == SERVER_QUANTIZE_TYPES
    assert VARIANTS["int4+rot"].quantize_type == "int4" and VARIANTS["int4+rot"].enable_rotate


def test_default_variants_all_build_on_hnsw() -> None:
    hnsw = CollectionSpec(name="c", dim=128, index="hnsw", metric="l2")
    assert all(skip_reason(VARIANTS[v], hnsw) is None for v in DEFAULT_VARIANTS)
    assert "pq4+fs" not in DEFAULT_VARIANTS


def test_skip_reason_index_metric_dtype() -> None:
    hnsw = CollectionSpec(name="c", dim=128, index="hnsw", metric="l2")
    assert skip_reason(VARIANTS["pq4+fs"], hnsw) is not None
    assert skip_reason(VARIANTS["pq4+fs"], CollectionSpec(name="c", dim=8, index="ivf")) is None
    cosine = CollectionSpec(name="c", dim=8, index="hnsw", metric="cosine")
    assert "metric l2" in (skip_reason(VARIANTS["uint8"], cosine) or "")
    fp16 = CollectionSpec(name="c", dim=8, dtype="VECTOR_FP16")
    assert "VECTOR_FP32" in (skip_reason(VARIANTS["pq"], fp16) or "")
    flat = CollectionSpec(name="c", dim=8, index="flat")
    assert skip_reason(VARIANTS["pq"], flat) is not None
    assert skip_reason(VARIANTS["int8"], flat) is None


def test_apply_variant_pq_params() -> None:
    base = CollectionSpec(name="c", dim=128, index="hnsw", m=16)
    pq = apply_variant(base, VARIANTS["pq+opq"])
    assert pq.index_params() == {
        "m": 16,
        "quantize_type": "pq",
        "enable_rotate": True,
        "num_chunk": 32,
        "num_bits": 8,
    }
    assert apply_variant(base, VARIANTS["pq4"], pq_chunks=64).quantizer_params() == {
        "num_chunk": 64,
        "num_bits": 4,
    }
    ivf = CollectionSpec(name="c", dim=64, index="ivf")
    assert apply_variant(ivf, VARIANTS["pq4+fs"]).index_params() == {
        "quantize_type": "pq",
        "num_chunk": 16,
        "num_bits": 4,
        "fast_scan": True,
    }
    # Non-PQ variants carry no PQ params.
    assert apply_variant(base, VARIANTS["uint8"]).index_params() == {
        "m": 16,
        "quantize_type": "uniform_uint8",
    }


def test_server_query_params_refiner() -> None:
    assert server_query_params("hnsw", ef=200, nprobe=None) == {"ef": 200}
    assert server_query_params("hnsw", ef=200, nprobe=None, refine=0.0) == {
        "ef": 200,
        "is_using_refiner": True,
        "scale_factor": 0.0,
    }
    assert server_query_params("ivf", ef=None, nprobe=10, refine=10.0) == {
        "nprobe": 10,
        "is_using_refiner": True,
        "scale_factor": 10.0,
    }
    assert server_query_params("flat", ef=None, nprobe=None, refine=1.0) is None


def test_table_reports_recall_delta_against_fp32() -> None:
    table = _table([_row("fp32", 0.95), _row("int8", 0.93)], recall_k=10)
    lines = table.splitlines()
    assert "recall@10" in lines[0]
    assert "| fp32 |" in lines[2] and "+0.000" in lines[2]
    assert "| int8 |" in lines[3] and "-0.020" in lines[3]


def test_table_refine_column_and_delta_vs_unrefined_fp32() -> None:
    table = _table([_row("fp32", 0.95), _row("pq", 0.97, refine=0.0)], recall_k=10)
    lines = table.splitlines()
    assert "refine" in lines[0]
    assert "| pq |" in lines[3] and "| 0 |" in lines[3] and "+0.020" in lines[3]
