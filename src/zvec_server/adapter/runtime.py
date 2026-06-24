"""Process-wide Zvec engine initialization.

Zvec must be initialized exactly once per process; a second ``zvec.init`` call
raises ``RuntimeError``. Because integration tests spin up several FastAPI apps
inside one interpreter, :func:`init_zvec` is idempotent and defensively swallows
the "already initialized" ``RuntimeError``.
"""

from __future__ import annotations

import zvec

from zvec_server.logging import get_logger

logger = get_logger(__name__)

# Module-global guard: flips to True after the first successful init.
_initialized: bool = False

# Map our (Python-logging-style) level names to Zvec's LogLevel members. Note
# Zvec uses ``WARN`` rather than ``WARNING``.
_LOG_LEVELS: dict[str, str] = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARN",
    "WARN": "WARN",
    "ERROR": "ERROR",
    "CRITICAL": "FATAL",
    "FATAL": "FATAL",
}


def _resolve_log_level(level: str) -> zvec.LogLevel:
    """Translate a log-level string into a ``zvec.LogLevel`` member.

    Falls back to ``WARN`` for unknown values.
    """
    name = _LOG_LEVELS.get((level or "").upper(), "WARN")
    return zvec.LogLevel.__members__[name]


def init_zvec(
    *,
    log_level: str = "WARNING",
    log_dir: str | None = None,
    memory_limit_mb: int | None = None,
    query_threads: int | None = None,
    optimize_threads: int | None = None,
) -> None:
    """Initialize the Zvec engine once for the lifetime of the process.

    Subsequent calls are silent no-ops. Any ``RuntimeError`` from ``zvec.init``
    (e.g. the engine was already initialized by another code path) is swallowed
    and treated as success.

    Args:
        log_level: Logging verbosity (Python-style names accepted; ``WARNING``
            maps to Zvec's ``WARN``).
        log_dir: Directory for Zvec's own log files, or None.
        memory_limit_mb: Soft memory budget in MB, or None for the default.
        query_threads: Thread count for queries, or None for the default.
        optimize_threads: Thread count for background optimization, or None.
    """
    global _initialized
    if _initialized:
        return

    try:
        zvec.init(
            log_level=_resolve_log_level(log_level),
            log_dir=log_dir,
            memory_limit_mb=memory_limit_mb,
            query_threads=query_threads,
            optimize_threads=optimize_threads,
        )
    except RuntimeError as exc:
        # Already initialized elsewhere in this process; treat as success.
        logger.debug("zvec.init raised RuntimeError, assuming already initialized: %s", exc)
    else:
        logger.info("Zvec engine initialized (log_level=%s)", log_level)

    _initialized = True


def is_initialized() -> bool:
    """Return whether :func:`init_zvec` has run in this process."""
    return _initialized
