"""Console entry point: ``zvec-server`` / ``python -m zvec_server``."""

from __future__ import annotations

import uvicorn

from zvec_server.config import get_settings


def main() -> None:
    """Run the server with Uvicorn using a single worker.

    A single worker is intentional: open Zvec collection handles are
    process-local and not safe to share across worker processes. Scale with
    threads (the server offloads blocking engine work to a threadpool), or run
    multiple independent instances behind a router that shards by collection.
    """
    settings = get_settings()
    uvicorn.run(
        "zvec_server.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=1,
        log_config=None,
    )


if __name__ == "__main__":
    main()
