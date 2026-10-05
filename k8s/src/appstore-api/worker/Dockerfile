# AppStore worker image: the Python worker plus the tools its jobs run.
# Build context is the repository root:
#   docker build -f worker/Dockerfile .

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY backend/pyproject.toml backend/
COPY worker/pyproject.toml worker/
RUN uv sync --frozen --no-dev --package appstore-worker --no-install-workspace

COPY shared shared
COPY worker worker
RUN uv sync --frozen --no-dev --package appstore-worker --no-editable

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ARG TARGETARCH
ARG TOFU_VERSION=1.12.6
ARG PACKER_VERSION=1.16.1

# `apt-get upgrade`: see backend/Dockerfile.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    git \
    unzip \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The OpenStack CLI is called as a program (image lookups, server
# start/stop), so it lives in the system interpreter, apart from the
# worker's own venv and its pins.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir python-openstackclient

# OpenTofu, not Terraform (plan D5). Checked against the release's SHA256SUMS.
RUN ARCH="${TARGETARCH:-amd64}" && cd /tmp && \
    BASE=https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION} && \
    curl -fsSLO ${BASE}/tofu_${TOFU_VERSION}_linux_${ARCH}.zip && \
    curl -fsSLO ${BASE}/tofu_${TOFU_VERSION}_SHA256SUMS && \
    grep " tofu_${TOFU_VERSION}_linux_${ARCH}.zip\$" tofu_${TOFU_VERSION}_SHA256SUMS | sha256sum -c - && \
    unzip -qo tofu_${TOFU_VERSION}_linux_${ARCH}.zip tofu -d /usr/local/bin && \
    rm tofu_${TOFU_VERSION}_* && \
    tofu --version

RUN ARCH="${TARGETARCH:-amd64}" && \
    curl -fsSLo /tmp/packer.zip https://releases.hashicorp.com/packer/${PACKER_VERSION}/packer_${PACKER_VERSION}_linux_${ARCH}.zip && \
    unzip -qo /tmp/packer.zip packer -d /usr/local/bin && rm /tmp/packer.zip && \
    packer --version

COPY --from=builder /app/.venv /app/.venv

# pip goes after the OpenStack CLI is installed with it: see backend/Dockerfile.
RUN /app/.venv/bin/python -m pip uninstall -y pip 2>/dev/null; \
    /usr/local/bin/python -m pip uninstall -y pip

WORKDIR /app
# Job directories (one per deployment, handed to the slot's user) and the
# slot users' homes. Traversable, not listable, for the slot users.
RUN mkdir -p /tmp/worker_repos /var/lib/appstore-worker && \
    chmod 0711 /tmp/worker_repos /var/lib/appstore-worker

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORKER_JOB_UID_BASE=20000

# The worker runs as root (.trivyignore AVD-DS-0002) for one reason: to run
# each job's tools as their own unprivileged user (UID 20000 + slot, see
# appstore_worker/job_context.py). An app's OpenTofu code is untrusted, and
# that separation is what keeps it away from the worker's database URL and
# Fernet key and from the job next to it. The pod needs the default
# SETUID/SETGID/CHOWN capabilities for that, nothing more.
# Polls the tasks table (see appstore_worker/runner.py). On SIGTERM it stops
# claiming and finishes running jobs, so give the pod a long grace period.
CMD ["python", "-m", "appstore_worker"]
