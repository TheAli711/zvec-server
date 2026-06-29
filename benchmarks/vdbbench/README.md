# Track B — VectorDBBench parity (REST)

This directory is a **client plugin** for
[VectorDBBench](https://github.com/zilliztech/VectorDBBench) that points the
community-standard harness at a running **Zvec Server** over its REST API. The
QPS / recall / build-time numbers it produces are directly comparable to the
figures published on [zvec.org](https://zvec.org), which run VectorDBBench on
the Cohere 1M / 10M datasets.

Track B measures **only the served (network) path**: every operation crosses
loopback TCP, FastAPI/Pydantic, the adapter, and JSON (de)serialization of the
float vectors. For the in-process-vs-network decomposition (engine → in-proc →
http), use **Track A**: `uv run python -m benchmarks run`.

---

## 1. Install VectorDBBench (manual, heavy, separate)

VectorDBBench is **not** a dependency of this project and is intentionally not in
`pyproject.toml`. It is large (pulls Streamlit, plotting, many DB drivers), so
install it yourself — ideally in its **own** virtualenv so it does not collide
with the server's environment:

```bash
python -m venv ~/.venvs/vdbbench
source ~/.venvs/vdbbench/bin/activate
pip install vectordb-bench        # PyPI dist name; import name is vectordb_bench
```

Make this repo importable from that venv (so the plugin can be imported):

```bash
# from the repo root, with the vdbbench venv active:
pip install -e .                  # or: export PYTHONPATH=$PWD
```

Project / docs: <https://github.com/zilliztech/VectorDBBench>.

## 2. Start a Zvec Server

In a **separate** shell (the server uses the project's own `uv` environment),
start the server with auth disabled and note the host/port:

```bash
ZVEC_SERVER_AUTH_ENABLED=false uv run zvec-server --host 127.0.0.1 --port 8000
```

The defaults are `127.0.0.1:8000`, which is what the snippet below assumes.

## 3. Register the client and run a case

VectorDBBench has no plugin-discovery hook — built-in clients are wired through
the `DB` enum in `vectordb_bench/backend/clients/__init__.py`. Rather than fork
the package, register at runtime by handing our classes straight to a
`TaskConfig`. Run this from the **vdbbench venv**:

```python
from vectordb_bench.backend.clients.api import MetricType
from vectordb_bench.backend.cases import CaseType
from vectordb_bench.models import CaseConfig, TaskConfig
from vectordb_bench.interface import BenchMarkRunner
from vectordb_bench.backend.clients import DB

from benchmarks.vdbbench.zvec_rest_client import (
    ZvecRest,
    ZvecRestConfig,
    ZvecRestHNSWConfig,
)

# --- register our client by overriding an existing DB enum member's lookups ---
# The `db` field on TaskConfig is only used to look the client/config classes
# back up; any member works once we point its properties at our classes.
_DB = DB.Milvus  # placeholder enum value
type(_DB).init_cls = property(lambda self: ZvecRest)
type(_DB).config_cls = property(lambda self: ZvecRestConfig)
type(_DB).case_config_cls = lambda self, index_type=None: ZvecRestHNSWConfig

# --- connection + per-case params (mirror zvec.org headline settings) ---------
db_config = ZvecRestConfig(host="127.0.0.1", port=8000)
case_config = ZvecRestHNSWConfig(
    metric_type=MetricType.COSINE,   # Cohere is cosine
    M=15,                            # Cohere 1M: M=15, ef=180  (10M: M=50, ef=118)
    efConstruction=200,
    ef=180,
)

task = TaskConfig(
    db=_DB,
    db_config=db_config,
    db_case_config=case_config,
    case_config=CaseConfig(case_id=CaseType.Performance768D1M),  # Cohere 1M
)

BenchMarkRunner().run([task])
```

`Performance768D1M` is the Cohere 1M case (768-dim); use `Performance768D10M`
for 10M. Sweep the QPS–recall curve by re-running with different `ef` values
(e.g. `90, 120, 180, 240`); `M` / `efConstruction` control the build and feed
the create-collection request, while `ef` controls each query — all of them come
from `ZvecRestHNSWConfig` so sweeps just work.

> The exact `DB`/`TaskConfig`/`CaseType` import paths above match the
> `vectordb-bench` v0.0.20 release line. If your installed version differs,
> check `vectordb_bench/models.py` and `vectordb_bench/backend/cases.py`; the
> three `ZvecRest*` classes implement the stable `VectorDB` / `DBConfig` /
> `DBCaseConfig` ABCs and are forward-compatible with `main` (the client
> tolerates the newer `insert_embeddings` / `search_embedding` / `optimize`
> signatures).

## 4. Filtered cases

VectorDBBench's filtered cases pass `filters={"id": <int>}`, meaning `id >= X`.
The client mirrors each document's integer id into an indexed `id` scalar field
and translates the filter to the server's SQL-like string `id >= <int>`, so
filtered Performance cases work without extra setup.

## 5. Comparability and the int8 caveat

These numbers are comparable to the zvec.org Cohere 1M / 10M results because
they use the **same harness, datasets, and recall definition**.

**int8 caveat:** zvec.org's published Cohere runs use **int8** quantization. The
server's REST create-collection schema does **not** expose a quantize / scalar-
quantization parameter today, so Track B runs **`VECTOR_FP32`** over REST.
Recall matches fp32, but absolute QPS and memory will differ from an int8 run
until the server adds a quantization parameter to the create-collection body. At
that point this client can set `dtype` / pass the quantize param and the int8
numbers become reproducible over REST too.
