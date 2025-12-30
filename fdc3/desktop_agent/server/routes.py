# HTTP route handlers for the FDC3 Desktop Agent server

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/admin")
async def admin_page(request: Request):
    """Admin page for managing launch configurations"""
    return RedirectResponse(url=str(request.url_for("ui", path="admin.html")))


@router.get("/app-directory")
async def app_directory_page(request: Request):
    """App directory management interface"""
    return RedirectResponse(url=str(request.url_for("ui", path="app_directory.html")))


@router.get("/system-settings")
async def system_settings_page(request: Request):
    """System configuration panel"""
    return RedirectResponse(
        url=str(request.url_for("ui", path="system_settings.html"))
    )


@router.get("/diagnostics")
async def diagnostics_page(request: Request):
    """System diagnostics and health checks"""
    return RedirectResponse(url=str(request.url_for("ui", path="diagnostics.html")))


@router.get("/channel-monitor")
async def channel_monitor_page(request: Request):
    """Channel monitor UI for subscribing to channel events"""
    return RedirectResponse(
        url=str(request.url_for("ui", path="channel_monitor.html"))
    )


@router.get("/channel-sequence")
async def channel_sequence_page(request: Request):
    """Sequence diagram view for channel traffic (uses GraphQL subscription)."""
    return RedirectResponse(
        url=str(request.url_for("ui", path="sequence_diagram.html"))
    )


@router.get("/public-channels")
async def public_channels_page(request: Request):
    """Public channels management interface"""
    return RedirectResponse(
        url=str(request.url_for("ui", path="public_channels.html"))
    )
