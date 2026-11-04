# syntax=docker/dockerfile:1
#
# Tribos sandbox image: the isolation boundary for model-written code.
#
#   docker build -f docker/sandbox.Dockerfile -t tribos-sandbox:local .
#
# This image is NOT the API image. It contains no server code, no credentials, no model runtime and no
# network client: only the scientific stack the AST policy allows model-written code to import. The API
# container holds the credentials and must never execute model-written code; the executor container holds
# nothing but a Python interpreter and the scientific stack, and runs with no network at all.
#
# The runtime isolation comes from the flags the backend passes (docker/sandbox-runtime.md, and
# tribos/agentic/sandbox/container.py): --network none, --read-only, tmpfs /tmp and /work, --memory, --cpus,
# --pids-limit, --cap-drop ALL, --security-opt no-new-privileges, --user nobody. The image itself is built
# to cooperate with that: a non-root user, no shell tooling, and a writable home the tmpfs can overlay.
#
# Pin this image by digest in production: `docker inspect --format '{{index .RepoDigests 0}}' tribos-sandbox:local`.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.12.7

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------------------------------------
# Builder: install the pinned scientific stack into /opt/sandbox/venv.
# ---------------------------------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/sandbox/venv \
    UV_NO_DEV=1

WORKDIR /build

COPY docker/sandbox-requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
  uv pip install --python /usr/local/bin/python3 --requirement sandbox-requirements.txt

# ---------------------------------------------------------------------------------------------------------
# Runtime: the interpreter, the scientific stack and nothing else.
# ---------------------------------------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# libgomp1 is the OpenMP runtime the numeric stack links against; without it the wheels import but crash.
# Nothing here is a shell, a compiler or a network tool: the container runs one command and nothing else.
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libgomp1 \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --system --gid 65534 nobody \
  && useradd --system --uid 65534 --gid 65534 --home-dir /tmp --no-create-home --shell /usr/sbin/nologin nobody \
  && mkdir -p /work /io /out \
  && chmod 1777 /work /io /out

COPY --from=builder /opt/sandbox/venv /opt/sandbox/venv

ENV PATH="/opt/sandbox/venv/bin:${PATH}" \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    TMPDIR=/tmp \
    HOME=/tmp

# The code runs as nobody (65534), matching CONTAINER_USER in tribos/agentic/sandbox/container.py.
USER 65534:65534

WORKDIR /work

# The bootstrap is written into /io by the backend at run time and executed with `python -I`, so this image
# needs no server code at all: an interpreter, the scientific stack and a writable scratch area.
ENTRYPOINT []
CMD ["python", "-c", "print('tribos sandbox image ready')"]
