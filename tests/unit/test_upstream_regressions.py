"""Canaries for known Zvec bugs that the server works around.

Each test reproduces the bug directly against the engine and is marked
``xfail(strict=True)``: while the bug exists the test "fails as expected"; once
an upstream release fixes it, the test passes and strict mode turns that into a
failure, which is the signal to remove the server-side guard.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
import zvec

from zvec_server.adapter import runtime

runtime.init_zvec()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "alibaba/zvec#886: hnsw + int8 + enable_rotate returns wrong results after "
        "optimize on Zvec 0.8.x. If this passes, lift the guard in "
        "schema_mapper._check_rotation (ZS-076)."
    ),
)
def test_hnsw_int8_rotation_recall_after_optimize(tmp_path: Path) -> None:
    rng = random.Random(0)
    dim = 32
    vecs = {str(i): [rng.gauss(0, 1) for _ in range(dim)] for i in range(300)}
    index_param = zvec.HnswIndexParam(
        metric_type=zvec.MetricType.COSINE,
        quantize_type=zvec.QuantizeType.INT8,
        quantizer_param=zvec.QuantizerParam(enable_rotate=True),
    )
    schema = zvec.CollectionSchema(
        name="canary",
        vectors=[zvec.VectorSchema("e", zvec.DataType.VECTOR_FP32, dim, index_param=index_param)],
    )
    collection = zvec.create_and_open(str(tmp_path / "c"), schema)
    try:
        collection.insert([zvec.Doc(id=k, vectors={"e": v}) for k, v in vecs.items()])
        collection.optimize()
        hits = sum(
            collection.query(zvec.Query(field_name="e", vector=vecs[str(i)]), topk=1)[0].id
            == str(i)
            for i in range(50)
        )
    finally:
        collection.close()
    # 0.7.0 gives 50/50; the buggy 0.8.x builds give ~0.
    assert hits >= 45
