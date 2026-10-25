# syntax=docker/dockerfile:1
#
# Tribos Clinical R&D API (FastAPI + uvicorn).
#
#   docker build -f docker/backend.Dockerfile -t tribos-backend .     (context = repo root)
#
# This image replaces the legacy Streamlit image in tribos/tribos/Dockerfile for the API. Dependencies
# come from uv.lock (`uv sync --frozen`), so the image matches CI. The lock pins torch and other heavy
# scientific packages, so expect a large image (several GB).

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.12.7

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------------------------------------
# Builder: resolve and install the locked runtime dependencies into /app/.venv.
# ---------------------------------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential git \
  && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (cached layer), project source second. --no-install-project: the app runs from the
# copied source tree on PYTHONPATH, so the wheel build (and its sdist/wheel include lists) is not needed.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------------------------------------
# Runtime: slim image, non-root user, source + venv only.
# ---------------------------------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --system --gid 10001 tribos \
  && useradd --system --uid 10001 --gid tribos --home-dir /home/tribos --create-home tribos \
  && mkdir -p /data \
  && chown tribos:tribos /data

WORKDIR /app

COPY --from=builder --chown=tribos:tribos /app/.venv /app/.venv
COPY --chown=tribos:tribos tribos/ ./tribos/
COPY --chown=tribos:tribos app/ ./app/

# All mutable state lives on the /data volume. TRIBOS_DATA_DIR is the umbrella; the stores below are the
# variables the code actually reads (run provenance, jobs, memory, projects, tool cache).
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRIBOS_DATA_DIR=/data \
    TRIBOS_RUNS_DIR=/data/runs \
    TRIBOS_JOBS_DIR=/data/jobs \
    TRIBOS_MEMORY_DIR=/data/memory \
    TRIBOS_PROJECTS_DIR=/data/projects \
    TRIBOS_TOOL_CACHE_DIR=/data/tool_cache \
    HOME=/home/tribos

VOLUME ["/data"]

USER tribos

EXPOSE 8000

# /api/health/live makes no upstream calls, so it stays cheap and does not flap when a source is down.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health/live || exit 1

CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
