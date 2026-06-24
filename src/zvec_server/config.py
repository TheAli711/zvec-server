"""Application configuration.

Settings are loaded from environment variables (prefix ``ZVEC_SERVER_``) and an
optional ``.env`` file. Derived paths (metadata DB, collections root) are filled
in automatically from ``data_dir`` when not explicitly provided, so downstream
code can always rely on ``settings.metadata_db_path`` and
``settings.collections_dir`` being concrete :class:`pathlib.Path` objects.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogFormat = Literal["json", "console"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Server configuration resolved from the environment.

    Attributes are populated from ``ZVEC_SERVER_*`` environment variables (or a
    ``.env`` file). See ``.env.example`` for the full list.
    """

    model_config = SettingsConfigDict(
        env_prefix="ZVEC_SERVER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Storage ---
    data_dir: Path = Path("./data")
    metadata_db_path: Path | None = None
    collections_dir: Path | None = None

    # --- HTTP server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Logging ---
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    # --- Zvec engine ---
    enable_mmap: bool = True
    zvec_memory_limit_mb: int | None = None
    zvec_query_threads: int | None = None
    zvec_optimize_threads: int | None = None
    zvec_log_dir: Path | None = None

    # --- Authentication ---
    # When ``auth_enabled`` is true, every request (except the health/readiness
    # probes) must send ``Authorization: Bearer <api_key>``. The key is supplied
    # out-of-band via the environment / a secret manager and never persisted by
    # the server. See ``zvec_server.auth`` for the (pluggable) provider.
    auth_enabled: bool = False
    # Wrapped in SecretStr so the key is never exposed by ``repr(settings)``,
    # ``model_dump()``, or tracebacks — only ``get_secret_value()`` reveals it.
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def _fill_derived_paths(self) -> Settings:
        """Resolve metadata DB and collections paths relative to ``data_dir``."""
        if self.metadata_db_path is None:
            self.metadata_db_path = self.data_dir / "metadata.db"
        if self.collections_dir is None:
            self.collections_dir = self.data_dir / "collections"
        return self

    @model_validator(mode="after")
    def _validate_auth(self) -> Settings:
        """Require an API key whenever authentication is enabled."""
        if self.auth_enabled and not (self.api_key and self.api_key.get_secret_value().strip()):
            raise ValueError(
                "ZVEC_SERVER_API_KEY must be set (non-empty) when ZVEC_SERVER_AUTH_ENABLED is true."
            )
        return self

    def ensure_directories(self) -> None:
        """Create the data, collections, and metadata-DB parent directories."""
        assert self.metadata_db_path is not None  # set by validator
        assert self.collections_dir is not None  # set by validator
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
