"""FastAPI application factory and lifespan.

The lifespan wires up the process-wide singletons in order: structured logging,
the one-time Zvec engine init, the SQLite metadata store, and the
:class:`CollectionManager` (which opens all registered collections). These are
stored on ``app.state`` for dependency injection and torn down cleanly on
shutdown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from zvec_server import __version__
from zvec_server.adapter.runtime import init_zvec
from zvec_server.api import collections as collections_api
from zvec_server.api import health as health_api
from zvec_server.api import vectors as vectors_api
from zvec_server.auth import AuthMiddleware, build_auth_provider
from zvec_server.config import Settings, get_settings
from zvec_server.db.metadata import MetadataStore
from zvec_server.errors import register_exception_handlers
from zvec_server.logging import configure_logging, get_logger
from zvec_server.manager import CollectionManager

logger = get_logger(__name__)

_DESCRIPTION = """
A lightweight, storage-focused HTTP API over the
[Zvec](https://github.com/alibaba/zvec) vector database.

Manage collections, write documents (insert/upsert/update/delete), fetch by id,
and run vector similarity search with SQL-like filters. The server stores
**client-supplied vectors only** — it does not generate embeddings.

Authentication is optional and off by default. When enabled
(`ZVEC_SERVER_AUTH_ENABLED=true`), every request except the health/readiness
probes must send an `Authorization: Bearer <api_key>` header. Always deploy
behind TLS / a trusted network or gateway.
""".strip()

_TAGS_METADATA = [
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "collections", "description": "Create, inspect, and delete collections."},
    {"name": "documents", "description": "Write, fetch, delete, and search documents."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override (tests pass a temporary data dir).
            Falls back to the cached environment-derived settings.

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved.log_level, resolved.log_format)
        init_zvec(
            log_level=resolved.log_level,
            log_dir=str(resolved.zvec_log_dir) if resolved.zvec_log_dir else None,
            memory_limit_mb=resolved.zvec_memory_limit_mb,
            query_threads=resolved.zvec_query_threads,
            optimize_threads=resolved.zvec_optimize_threads,
        )
        resolved.ensure_directories()
        assert resolved.metadata_db_path is not None  # set by Settings validator

        store = MetadataStore(resolved.metadata_db_path)
        store.connect()
        manager = CollectionManager(resolved, store)
        manager.load_all()

        app.state.settings = resolved
        app.state.store = store
        app.state.manager = manager
        app.state.ready = True
        logger.info(
            "Zvec Server ready",
            extra={
                "host": resolved.host,
                "port": resolved.port,
                "auth": "api_key" if resolved.auth_enabled else "disabled",
            },
        )
        try:
            yield
        finally:
            app.state.ready = False
            manager.close()
            store.close()
            logger.info("Zvec Server stopped")

    app = FastAPI(
        title="Zvec Server",
        description=_DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        openapi_tags=_TAGS_METADATA,
    )

    auth_provider = build_auth_provider(resolved)
    if auth_provider.enabled:
        app.add_middleware(AuthMiddleware, provider=auth_provider)

    register_exception_handlers(app)
    app.include_router(health_api.router)
    app.include_router(collections_api.router)
    app.include_router(vectors_api.router)
    return app


#: Module-level app for ``uvicorn zvec_server.app:app``. The factory form
#: (``--factory zvec_server.app:create_app``) is preferred for custom settings.
app = create_app()
