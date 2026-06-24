"""FastAPI dependencies that expose the per-process singletons stored on
``app.state`` (set up by the application lifespan).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from zvec_server.db.metadata import MetadataStore
    from zvec_server.manager import CollectionManager


def get_manager(request: Request) -> CollectionManager:
    """Return the process-wide :class:`CollectionManager`."""
    manager: CollectionManager = request.app.state.manager
    return manager


def get_metadata(request: Request) -> MetadataStore:
    """Return the process-wide :class:`MetadataStore`."""
    store: MetadataStore = request.app.state.store
    return store
