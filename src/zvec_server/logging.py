"""Structured logging configuration.

Supports two output formats:

* ``json``    — one JSON object per line (production / log aggregation).
* ``console`` — a compact human-readable line (local development).
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure the root logger and align uvicorn loggers with our handler.

    Args:
        level: Minimum log level name (e.g. ``"INFO"``).
        fmt: ``"json"`` or ``"console"``.
    """
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "timestamp", "levelname": "level"},
                timestamp=True,
            )
        )
    else:
        handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Route uvicorn's loggers through our handler instead of its defaults so that
    # access/error logs share the same structured format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [handler]
        uv_logger.propagate = False
        uv_logger.setLevel(level.upper())


def get_logger(name: str = "zvec_server") -> logging.Logger:
    """Return a named application logger."""
    return logging.getLogger(name)
