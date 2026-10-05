# AppStore API image. Build context is the repository root:
#   docker build -f backend/Dockerfile .
# so the shared package and the one lockfile of the workspace are in reach.

# ---------------------------------------------------------------------------
# Builder: resolve exactly what uv.lock says, nothing else.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

# Non-editable installs, so the runtime stage needs the venv only, not the
# sources it was built from. Bytecode is compiled here, once, instead of by
# every container start.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# Dependencies first, as their own layer: they change far less often than
# the code.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY backend/pyproject.toml backend/
COPY worker/pyproject.toml worker/
RUN uv sync --frozen --no-dev --package appstore-api --no-install-workspace

COPY shared shared
COPY backend backend
COPY VERSION backend/appstore_api/VERSION
RUN uv sync --frozen --no-dev --package appstore-api --no-editable

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# A fixed, numeric UID: Kubernetes can only enforce runAsNonRoot for a number.
RUN groupadd -r -g 10001 appuser && useradd -r -u 10001 -g appuser appuser

# `apt-get upgrade` picks up Debian security backports released after the
# base tag was built. Trivy blocks the push on HIGH/CRITICAL OS findings, and
# taking the extra bytes beats a .trivyignore line per upstream fix.
# git: listing and sparse-cloning app repositories.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv

# pip ships a CycloneDX SBOM of its vendored libraries that Trivy reports as
# if they were installed. A runtime image installs nothing, so pip goes. Both
# interpreters, because PATH puts the venv first.
RUN /app/.venv/bin/python -m pip uninstall -y pip 2>/dev/null; \
    /usr/local/bin/python -m pip uninstall -y pip

WORKDIR /app
# Migrations run from the same image (`alembic upgrade head`), so the chart
# needs no second one for that.
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

RUN mkdir -p /tmp/worker_repos && chown appuser:appuser /tmp/worker_repos

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 10001
EXPOSE 8000

# One process per container; scale with replicas.
CMD ["uvicorn", "appstore_api.main:app", "--host", "::", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
