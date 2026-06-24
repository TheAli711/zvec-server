---
id: ZS-024
title: Runnable examples: Python client and curl script
spec: SPEC-006
type: docs
priority: P2
status: done
release: v0.1.0
created: 2026-06-18
closed: 2026-06-24
---

# ZS-024: Runnable examples: Python client and curl script

## Summary

Add two end-to-end examples that a new user can run against a local server: a Python
script using `httpx` and a pure-curl shell script. Both walk the full lifecycle so they
double as a smoke test of the API and as copy-paste material for real clients.

## Acceptance criteria

- [x] `examples/python_client.py` and `examples/curl_examples.sh` run health, create
      `articles_example`, insert, filtered search, fetch `a1` with its vector, update,
      delete `a3`, and drop the collection.
- [x] Both read `ZVEC_SERVER_URL` (default `http://localhost:8000`) and send
      `Authorization: Bearer $ZVEC_SERVER_API_KEY` when that variable is set.
- [x] The Python client drops the collection in a `finally` block and raises with the
      server's error body on any non-2xx response.
- [x] The curl script uses `set -euo pipefail`, pretty-prints with `jq` when available,
      and fails with the response body shown on HTTP status 400 or above.
- [x] `examples/README.md` explains prerequisites and how to run each example.

## Notes

- Vectors are 4-dim and hand-written; say explicitly that the server never generates
  embeddings.
- Comment the filter syntax at the search step (single `=`, single quotes, not `==`).
- The curl script must work on macOS's bash 3.2: expanding an empty auth-header array
  under `set -u` needs the `${arr[@]+"${arr[@]}"}` guard.
- `httpx` is a dev dependency; point users at `uv sync --extra dev`.

## Resolution

Added `examples/python_client.py`, `examples/curl_examples.sh`, and
`examples/README.md`. The search step passes `params: {"ef": 64}` to show HNSW tuning.
The examples README does not mention `ZVEC_SERVER_API_KEY`; the auth usage is documented
in each script's header instead.
