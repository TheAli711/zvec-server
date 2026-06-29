"""Tier 3 — the real server over the wire, end to end.

This drives a genuine ``uvicorn`` subprocess via ``httpx`` over loopback TCP, so
every call traverses the full FastAPI stack: ASGI dispatch, Pydantic request
parsing, the same ``adapter.operations.*`` work the in-proc tier runs, and JSON
serialization of the response back over the socket. The gap between this tier
and the in-proc tier is therefore the *transport tax* — and, for vector search,
the cost of shipping float arrays as JSON in both directions.

That JSON-over-vectors overhead is the whole reason this tier exists, so every
:class:`SearchOutcome` it produces reports the request and response payload
sizes in bytes (the in-proc tier leaves those ``None``).

The server runs single-worker with auth disabled, pointed at an isolated data
directory that is wiped and recreated on every ``setup``. A single shared
``httpx.Client`` is used for the whole run; ``httpx.Client`` is safe to call
concurrently from the harness's worker threads.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import IO

import httpx
import numpy as np

from benchmarks.runners.base import SearchOutcome
from benchmarks.spec import CollectionSpec

__all__ = ["HttpRunner"]

_READINESS_TIMEOUT_S = 30.0
_READINESS_POLL_S = 0.2


class HttpRunner:
    """Runner for the end-to-end HTTP tier (uvicorn subprocess + httpx client)."""

    name = "http"

    def __init__(
        self,
        data_dir: Path,
        *,
        port: int | None = None,
        query_threads: int | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._port = port if port is not None else _free_port()
        self._query_threads = query_threads
        self._proc: subprocess.Popen[bytes] | None = None
        self._client: httpx.Client | None = None
        self._spec: CollectionSpec | None = None
        self._log_path = self._data_dir / "server.log"
        self._log_file: IO[bytes] | None = None

    # ----------------------------------------------------------------- lifecycle
    def setup(self, spec: CollectionSpec) -> None:
        """Start a fresh server subprocess and create the collection from ``spec``."""
        if self._data_dir.exists():
            shutil.rmtree(self._data_dir, ignore_errors=True)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "zvec_server.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(self._port),
            "--workers",
            "1",
            "--log-level",
            "warning",
        ]
        env = {
            **os.environ,
            "ZVEC_SERVER_DATA_DIR": str(self._data_dir),
            "ZVEC_SERVER_LOG_FORMAT": "console",
            "ZVEC_SERVER_AUTH_ENABLED": "false",
        }
        if self._query_threads is not None:
            env["ZVEC_SERVER_ZVEC_QUERY_THREADS"] = str(self._query_threads)

        # Route the server's stdout/stderr to a log file rather than an
        # undrained PIPE: a PIPE's ~64 KB OS buffer fills under concurrent load
        # and blocks the server's logging write, deadlocking the event loop. A
        # file never blocks the writer and is still readable for diagnostics.
        self._log_file = self._log_path.open("wb")
        self._proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
        )

        self._wait_until_ready()

        self._client = httpx.Client(
            base_url=f"http://127.0.0.1:{self._port}",
            timeout=120.0,
        )
        self._spec = spec
        self._create_collection(spec)

    def teardown(self) -> None:
        """Drop the collection, close the client, and stop the subprocess."""
        if self._client is not None and self._spec is not None:
            with contextlib.suppress(Exception):
                self._client.delete(f"/collections/{self._spec.name}")
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        shutil.rmtree(self._data_dir, ignore_errors=True)

    def target_pid(self) -> int | None:
        """PID of the server subprocess whose RSS reflects the engine's memory."""
        return self._proc.pid if self._proc is not None else None

    # -------------------------------------------------------------------- writes
    def ingest(
        self,
        ids: list[str],
        vectors: np.ndarray,
        fields: list[dict[str, object]] | None,
    ) -> None:
        """Write one batch of documents via ``POST /collections/{name}/docs/insert``."""
        assert self._spec is not None
        field = self._spec.vector_field
        docs = [
            {
                "id": ids[i],
                "vectors": {field: vectors[i].tolist()},
                "fields": (fields[i] if fields is not None else {}),
            }
            for i in range(len(ids))
        ]
        self._post(f"/collections/{self._spec.name}/docs/insert", {"docs": docs})

    def optimize(self) -> None:
        """Flush buffered writes, then build/optimize the index."""
        assert self._spec is not None
        self._post(f"/collections/{self._spec.name}/flush", {})
        self._post(f"/collections/{self._spec.name}/optimize", {})

    # ------------------------------------------------------------------- queries
    def search(
        self,
        vector: np.ndarray,
        topk: int,
        *,
        ef: int | None = None,
        nprobe: int | None = None,
        filter: str | None = None,
        include_vector: bool = False,
    ) -> SearchOutcome:
        """Run one query and report the hit ids plus JSON payload byte counts."""
        assert self._client is not None and self._spec is not None
        params: dict[str, int] | None = {"ef": ef} if ef is not None else None
        body = {
            "queries": [
                {
                    "field": self._spec.vector_field,
                    "vector": vector.tolist(),
                    "params": params,
                }
            ],
            "topk": topk,
            "filter": filter,
            "include_vector": include_vector,
        }
        url = f"/collections/{self._spec.name}/search"
        content = json.dumps(body).encode()
        resp = self._client.post(
            url,
            content=content,
            headers={"content-type": "application/json"},
        )
        if not resp.is_success:
            raise RuntimeError(f"POST {url} -> {resp.status_code}: {resp.text}")
        results = resp.json()["results"]
        return SearchOutcome(
            ids=[r["id"] for r in results],
            request_bytes=len(content),
            response_bytes=len(resp.content),
        )

    # ------------------------------------------------------------------- helpers
    def _create_collection(self, spec: CollectionSpec) -> None:
        body = {
            "name": spec.name,
            "vectors": [
                {
                    "name": spec.vector_field,
                    "dim": spec.dim,
                    "dtype": spec.dtype,
                    "index": spec.index,
                    "metric": spec.metric,
                    "params": spec.index_params(),
                }
            ],
            "fields": [
                {
                    "name": f.name,
                    "dtype": f.dtype,
                    "indexed": f.indexed,
                    "nullable": f.nullable,
                }
                for f in spec.scalar_fields
            ],
            "options": {"enable_mmap": spec.enable_mmap},
        }
        self._post("/collections", body)

    def _post(self, url: str, body: dict[str, object]) -> httpx.Response:
        """POST a JSON body, raising a clear error on any non-2xx response."""
        assert self._client is not None
        resp = self._client.post(url, json=body)
        if not resp.is_success:
            raise RuntimeError(f"POST {url} -> {resp.status_code}: {resp.text}")
        return resp

    def _wait_until_ready(self) -> None:
        """Poll ``/readyz`` until the server answers 200 or the timeout elapses."""
        assert self._proc is not None
        deadline = time.monotonic() + _READINESS_TIMEOUT_S
        url = f"http://127.0.0.1:{self._port}/readyz"
        with httpx.Client(timeout=2.0) as probe:
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    raise RuntimeError(
                        f"Server exited early (code {self._proc.returncode}).\n"
                        f"{self._captured_logs()}"
                    )
                try:
                    if probe.get(url).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(_READINESS_POLL_S)
        raise RuntimeError(
            f"Server on port {self._port} not ready within {_READINESS_TIMEOUT_S:.0f}s.\n"
            f"{self._captured_logs()}"
        )

    def _captured_logs(self) -> str:
        """Best-effort read of the subprocess's log file for diagnostics."""
        if self._log_file is not None:
            with contextlib.suppress(Exception):
                self._log_file.flush()
        try:
            data = self._log_path.read_bytes()
        except Exception:
            return "<no logs captured>"
        return data.decode(errors="replace") if data else "<no output>"


def _free_port() -> int:
    """Return an OS-assigned free TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
