# HTTP route handlers for the FDC3 Desktop Agent server

from fastapi import APIRouter, Request, HTTPException
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
    return RedirectResponse(url=str(request.url_for("ui", path="system_settings.html")))


@router.get("/diagnostics")
async def diagnostics_page(request: Request):
    """System diagnostics and health checks"""
    return RedirectResponse(url=str(request.url_for("ui", path="diagnostics.html")))


@router.get("/channel-monitor")
async def channel_monitor_page(request: Request):
    """Channel monitor UI for subscribing to channel events"""
    return RedirectResponse(url=str(request.url_for("ui", path="channel_monitor.html")))


@router.get("/channel-sequence")
async def channel_sequence_page(request: Request):
    """Sequence diagram view for channel traffic (uses GraphQL subscription)."""
    return RedirectResponse(
        url=str(request.url_for("ui", path="sequence_diagram.html"))
    )


@router.get("/public-channels")
async def public_channels_page(request: Request):
    """Public channels management interface"""
    return RedirectResponse(url=str(request.url_for("ui", path="public_channels.html")))


@router.post("/admin/raise-intent")
async def admin_raise_intent(request: Request):
    """Raise an intent from the admin UI. Expects JSON {"intent": str, "context": dict}.

    This will resolve the intent using the core IntentResolver and deliver
    an IntentEvent to any matching connected instances. Returns the resolved
    IntentResolution and the list of instance UUIDs targeted.
    """
    body = await request.json()
    intent = body.get("intent")
    context = body.get("context")

    if not intent or not isinstance(intent, str):
        return {"error": "Missing or invalid 'intent' field"}

    core = request.app.state.core_services
    dacp_handler = getattr(request.app.state, "dacp_handler", None)

    resolution = core.intent_resolver.resolve_intent(intent, context, None)
    if resolution is None:
        return {"error": "NoAppsFound"}

    targets = core.intent_resolver.deliver_intent_event(intent, context, None)

    # Deliver intentEvent to each target instance via the DACP connection manager
    if dacp_handler is not None:
        from fdc3.models.dacp.dacp import (
            IntentEvent,
            IntentEventPayload,
            AgentEventMeta,
        )

        for target_uuid in targets:
            event = IntentEvent(
                type="intentEvent",
                payload=IntentEventPayload(
                    intent=intent, context=context, originatingApp=None
                ),
                meta=AgentEventMeta(),
            )
            # Send the serialized event to the instance
            try:
                await dacp_handler.connection_manager.send_to_instance(
                    target_uuid, event.model_dump_json()
                )
            except Exception:
                # Log and continue - failures to deliver should not cause full failure
                import logging

                logging.exception("Failed to deliver intentEvent to %s", target_uuid)

    return {"intentResolution": resolution.model_dump(), "targets": targets}


def _app_directory_entry(meta) -> dict:
    return {
        "appId": getattr(meta, "app_id", None) or getattr(meta, "appId", None),
        "name": getattr(meta, "name", None),
        "version": getattr(meta, "version", None),
        "description": getattr(meta, "description", None),
        "icons": getattr(meta, "icons", None) or [],
        "intents": getattr(meta, "intents", None) or [],
    }


@router.get("/v2/apps")
async def app_directory_list(request: Request):
    """List all apps in the local app directory (FDC3 App Directory v2 compatible)."""
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        return []
    try:
        apps = await storage.apps.list_apps()
    except Exception:
        return []
    return [_app_directory_entry(app) for app in apps if app is not None]


@router.get("/v2/apps/{app_id}")
async def app_directory_get(request: Request, app_id: str):
    """Get app metadata from the local app directory (FDC3 App Directory v2 compatible)."""
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=404, detail="App not found")
    try:
        meta = await storage.apps.get_app_metadata(app_id)
    except Exception:
        meta = None
    if not meta:
        raise HTTPException(status_code=404, detail="App not found")
    return _app_directory_entry(meta)
