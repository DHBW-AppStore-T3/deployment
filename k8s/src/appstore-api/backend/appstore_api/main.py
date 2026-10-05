"""The FastAPI application: lifespan, CORS, routers and the two public meta routes.

``uvicorn appstore_api.main:app`` serves it; :mod:`appstore_api.openapi`
imports it to write ``openapi.json``. Routes live in ``routers/``.
"""

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from appstore_api import __version__
from appstore_api.auth import sign_in_available
from appstore_api.config import settings
from appstore_api.openapi import operation_id
from appstore_api.routers import (
    admin_apps,
    apps,
    courses,
    deployments,
    internal_tfstate,
    openstack_credentials,
    openstack_resources,
    quotas,
    tasks,
    teams,
)
from appstore_api.services import task_finalizer

logger = logging.getLogger(__name__)


# ``DISABLE_BACKGROUND_TASKS`` short-circuits the lifespan body so the
# app is fully wired but the task finalizer loop is not started. Used by
# the test suite, where every TestClient would otherwise start another
# loop against the test database.
def _background_tasks_disabled() -> bool:
    return os.getenv("DISABLE_BACKGROUND_TASKS", "").lower() in ("1", "true", "yes")


# ----------------------------------------------------------------
# STARTUP/SHUTDOWN
# ----------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the task finalizer loop for as long as the app serves requests."""
    if _background_tasks_disabled():
        logger.info("DISABLE_BACKGROUND_TASKS set — not starting the task finalizer")
        yield
        return

    # Every replica runs it; the loop claims rows with SKIP LOCKED, so the
    # follow-up work of each task still happens once.
    finalizer = asyncio.create_task(task_finalizer.run_forever())
    try:
        yield
    finally:
        finalizer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await finalizer


# ----------------------------------------------------------------
# FASTAPI APP
# ----------------------------------------------------------------
app = FastAPI(
    title="AppStore API",
    description="App catalogue, deployments and teams for the DHBW cloud self-service platform",
    version=__version__,
    lifespan=lifespan,
    # Same place as the Go services'. Public: the description holds no data.
    openapi_url="/swagger.json",
    generate_unique_id_function=operation_id,
    # Behind the UI's proxy the API lives under /api/appstore (plan AP6);
    # the prefix is stripped before it arrives, this only fixes the links
    # the docs page builds.
    root_path=settings.API_ROOT_PATH,
)

# ----------------------------------------------------------------
# CORS
# ----------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------
# ROUTERS
# ----------------------------------------------------------------
app.include_router(apps.router, prefix="/apps", tags=["Apps"])
app.include_router(admin_apps.router, prefix="/admin", tags=["Admin"])
app.include_router(deployments.router, prefix="/deployments", tags=["Deployments"])
app.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
app.include_router(teams.router, prefix="/teams", tags=["Teams"])
app.include_router(courses.router)
app.include_router(quotas.router, tags=["OpenStack Credentials"])
app.include_router(openstack_credentials.router, tags=["OpenStack Credentials"])
# OpenTofu's state backend for the worker's jobs; not in the public API.
app.include_router(internal_tfstate.router, prefix="/internal/tfstate")
# Read API for OpenStack resources (Networks, Flavors, Images, ...),
# used by the wizard's value-help dropdowns so users don't have to type
# UUIDs from Horizon.
app.include_router(
    openstack_resources.router,
    prefix="/me/openstack-credentials/{credential_id}/resources",
    tags=["OpenStack Resources"],
)


# ----------------------------------------------------------------
# PUBLIC BOOTSTRAP CONFIG
# ----------------------------------------------------------------
@app.get("/config.json", tags=["Meta"])
def get_config():
    """Version and sign-in settings, without authentication.

    Same shape as openstack-management-api's. Public on purpose: an
    authenticated endpoint would fail exactly when ``sign_in_available`` is
    false and the UI needs to know.
    """
    return {
        "version": __version__,
        "auth": {
            "auth_provider": "oidc",
            "issuer_url": settings.OIDC_ISSUER_URL,
            "client_id": settings.OIDC_CLIENT_ID,
            "sign_in_available": sign_in_available(),
        },
    }


# ----------------------------------------------------------------
# HEALTH CHECK
# ----------------------------------------------------------------
@app.get("/health", tags=["Meta"])
def get_health():
    """Liveness probe: always ``healthy`` while the process answers; checks no dependencies."""
    return {
        "status": "healthy",
        "service": "appstore-api",
        "version": __version__,
    }
