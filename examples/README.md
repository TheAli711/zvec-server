# Examples

Runnable, end-to-end walkthroughs of the Zvec Server REST API. Both examples
perform the same flow: create a collection, insert documents, run a similarity
search with a SQL-like filter, fetch a document by id, update it, delete one, and
finally drop the collection.

> The server stores **client-supplied vectors only** — it does not generate
> embeddings. The vectors in these examples are small (4-dim) and hand-written
> for illustration. In a real app you would compute embeddings with your own
> model and send the resulting vectors.

## Prerequisites

Start a server first (from the project root):

```bash
# with uv
uv run zvec-server

# ...or with Docker Compose
docker compose up --build
```

By default both examples target `http://localhost:8000`. Override with the
`ZVEC_SERVER_URL` environment variable.

## Python client (`python_client.py`)

Uses [`httpx`](https://www.python-httpx.org/), which is already part of the
project's dev dependencies.

```bash
uv run python examples/python_client.py

# against a different server
ZVEC_SERVER_URL=http://localhost:8000 uv run python examples/python_client.py
```

If you only want runtime deps installed, `httpx` is available via the dev extra:
`uv sync --extra dev`.

## curl script (`curl_examples.sh`)

Pure `curl`; pretty-prints responses with `jq` if it is installed.

```bash
chmod +x examples/curl_examples.sh   # first time only
./examples/curl_examples.sh

# against a different server
ZVEC_SERVER_URL=http://localhost:8000 ./examples/curl_examples.sh
```

## See also

- [docs/API.md](../docs/API.md) — full request/response reference.
- [docs/CONFIGURATION.md](../docs/CONFIGURATION.md) — configuration variables.
