# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build — resolve and install dependencies with uv into /app/.venv
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

# Faster, more reproducible installs:
#   - compile bytecode for quicker cold starts
#   - copy (not link) packages so the venv is self-contained and portable
#     across the stage boundary
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install only third-party dependencies first, using the locked versions.
# This layer is cached and only rebuilt when pyproject.toml / uv.lock change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --no-dev --frozen --no-install-project

# Now copy the project source and install the project itself (the zvec_server
# package). Kept as a separate layer so source edits don't re-resolve deps.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen

# ---------------------------------------------------------------------------
# Stage 2: runtime — slim image carrying only the venv and the app source
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# curl is needed by the HEALTHCHECK below; clean apt lists to keep the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user. The /data volume is owned by this user so the
# server can persist collections and the metadata DB.
RUN groupadd --system --gid 1000 zvec \
    && useradd --system --uid 1000 --gid zvec --create-home zvec

WORKDIR /app

# Bring over the fully-built virtual environment and the application source.
COPY --from=build --chown=zvec:zvec /app/.venv /app/.venv
COPY --from=build --chown=zvec:zvec /app/src /app/src

# Put the venv first on PATH so `uvicorn` / `zvec-server` resolve to it.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Persist all data under the mounted volume.
    ZVEC_SERVER_DATA_DIR=/data

# Persistent storage for collections + SQLite metadata.
RUN mkdir -p /data && chown zvec:zvec /data
VOLUME /data

USER zvec

EXPOSE 8000

# Liveness probe hits the lightweight /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# IMPORTANT: run with a SINGLE worker.
# Collections are process-local: they are opened once at startup and kept in an
# in-memory registry (CollectionManager). Multiple workers would each hold their
# own registry and could open the same on-disk collection concurrently, which is
# unsafe. Scale by running more single-worker instances behind a load balancer
# only if they target distinct data directories. Use the app factory.
CMD ["uvicorn", "zvec_server.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
