"""API routers for TideWatch."""

from fastapi import APIRouter
from app.api import settings, containers, updates, history, backup, widget, events, analytics, restarts, system, cleanup, auth, oidc, scan, webhooks, dependencies

api_router = APIRouter(prefix="/api/v1")

# Authentication routes (public and protected endpoints)
api_router.include_router(auth.router, tags=["authentication"])
api_router.include_router(oidc.router, tags=["oidc"])

# API routes (protected by authentication when auth_mode != "none")
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(containers.router, prefix="/containers", tags=["containers"])
api_router.include_router(updates.router, prefix="/updates", tags=["updates"])
api_router.include_router(history.router, prefix="/history", tags=["history"])
api_router.include_router(backup.router, prefix="/backup", tags=["backup"])
api_router.include_router(restarts.router, prefix="/restarts", tags=["restarts"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(cleanup.router, prefix="/cleanup", tags=["cleanup"])
api_router.include_router(scan.router, prefix="/scan", tags=["scan"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(dependencies.router, tags=["dependencies"])
api_router.include_router(events.router, tags=["events"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(widget.router, tags=["widget"])

__all__ = ["api_router"]
