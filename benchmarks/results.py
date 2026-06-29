"""The result schema shared by the harness (writer) and the report (reader).

A single benchmark run produces one :class:`RunResult`, serialized to
``benchmarks/results/<scenario>-<timestamp>.json``. Keeping this in one place
means :mod:`benchmarks.report` can consume results without importing the
harness.
"""

from __future__ import annotations

import json
import platform
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "EnvInfo",
    "IngestResult",
    "RunResult",
    "SearchResult",
    "TierResult",
    "capture_env",
]


@dataclass
class EnvInfo:
    """Machine + software context, captured once per run for reproducibility."""

    timestamp: str
    hostname: str
    platform: str
    python_version: str
    zvec_version: str
    git_commit: str | None
    cpu_model: str
    cpu_physical: int | None
    cpu_logical: int | None
    ram_gb: float | None
    # Server knobs that materially affect numbers.
    zvec_query_threads: int | None = None
    anyio_threadpool: int | None = None
    enable_mmap: bool | None = None
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    """Outcome of the load phase for one tier."""

    n_docs: int
    batch_size: int
    seconds: float
    docs_per_sec: float
    optimize_seconds: float
    peak_rss_mb: float


@dataclass
class SearchResult:
    """Outcome of one search measurement point (a single grid cell) for a tier."""

    concurrency: int
    topk: int
    ef: int | None
    nprobe: int | None
    filter: str | None
    qps: float
    recall_at_k: float
    latency: dict[str, float | int]  # LatencyStats.as_dict()
    measured_queries: int
    peak_rss_mb: float
    # HTTP-only payload sizes (bytes); None for in-process tiers.
    avg_request_bytes: float | None = None
    avg_response_bytes: float | None = None


@dataclass
class TierResult:
    """All measurements for one tier (engine | inproc | http)."""

    tier: str
    ingest: IngestResult | None = None
    searches: list[SearchResult] = field(default_factory=list)


@dataclass
class RunResult:
    """Everything produced by one scenario run."""

    scenario: str
    dataset: str
    spec: dict[str, Any]
    env: EnvInfo
    tiers: list[TierResult] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False)

    def save(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.env.timestamp.replace(":", "").replace("-", "").replace(".", "_")
        path = out_dir / f"{self.scenario}-{stamp}.json"
        path.write_text(self.to_json())
        return path


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def capture_env(notes: dict[str, Any] | None = None, **server_knobs: Any) -> EnvInfo:
    """Snapshot the host + software environment into an :class:`EnvInfo`."""
    try:
        import zvec

        zvec_version = getattr(zvec, "__version__", "unknown")
    except Exception:
        zvec_version = "unavailable"

    cpu_model = platform.processor() or platform.machine()
    cpu_physical: int | None = None
    cpu_logical: int | None = None
    ram_gb: float | None = None
    try:
        import psutil

        cpu_physical = psutil.cpu_count(logical=False)
        cpu_logical = psutil.cpu_count(logical=True)
        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        pass

    return EnvInfo(
        timestamp=datetime.now(UTC).isoformat(),
        hostname=socket.gethostname(),
        platform=platform.platform(),
        python_version=sys.version.split()[0],
        zvec_version=zvec_version,
        git_commit=_git_commit(),
        cpu_model=cpu_model,
        cpu_physical=cpu_physical,
        cpu_logical=cpu_logical,
        ram_gb=ram_gb,
        notes=notes or {},
        **server_knobs,
    )
