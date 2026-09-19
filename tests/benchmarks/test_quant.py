"""Unit tests for the quantization sweep's variant table and report."""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")

from benchmarks.quant import VARIANTS, _table


def _row(variant: str, recall: float) -> dict[str, object]:
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
            }
        ],
    }


def test_variants_cover_every_quantize_type() -> None:
    assert VARIANTS["fp32"] == (None, False)
    assert {q for q, _ in VARIANTS.values()} == {None, "fp16", "int8", "int4"}
    assert VARIANTS["int4+rot"] == ("int4", True)


def test_table_reports_recall_delta_against_fp32() -> None:
    table = _table([_row("fp32", 0.95), _row("int8", 0.93)], recall_k=10)
    lines = table.splitlines()
    assert "recall@10" in lines[0]
    assert "| fp32 |" in lines[2] and "+0.000" in lines[2]
    assert "| int8 |" in lines[3] and "-0.020" in lines[3]
