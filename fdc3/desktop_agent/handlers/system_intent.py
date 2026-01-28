"""
System Intent Handler for FDC3 Desktop Agent.
Handles system-level intents that are built into the desktop agent itself.
"""

import logging
import os
import subprocess
from typing import Dict, Any, Optional
from pydantic import BaseModel
from fdc3.models.primitives import RequestUuid
from pathlib import Path

from fdc3.models.dacp.dacp import (
    AgentResponse,
    AgentResponseMeta,
    ErrorResponsePayload,
    RaiseIntentResponse,
    RaiseIntentResponsePayload,
)
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.identifiers import IntentResolution
from .protocols import MessageSender
from ..launcher.web_launcher import WebEndpointLauncher, WebBrowserLauncher

logger = logging.getLogger(__name__)


class SystemIntentHandler:
    """Handles system-level intents built into the desktop agent"""

    # System intent definitions
    SYSTEM_INTENTS = {
        # App Directory Management
        "fdc3.openAppDirectory": "open_app_directory",
        "fdc3.manageApps": "manage_apps",
        "fdc3.installApp": "install_app",
        "fdc3.uninstallApp": "uninstall_app",
        # System Configuration
        "fdc3.systemSettings": "system_settings",
        "fdc3.configureChannels": "configure_channels",
        "fdc3.systemDiagnostics": "system_diagnostics",
        # Channel Management
        "fdc3.createChannel": "create_channel",
        "fdc3.deleteChannel": "delete_channel",
        "fdc3.manageChannel": "manage_channel",
        # Built-in System Apps
        "fdc3.resolveIntent": "resolve_intent",
        # System Browser/File Manager
        "fdc3.openUrl": "open_url",
        "fdc3.openFile": "open_file",
        "fdc3.systemSearch": "system_search",
        # System Notifications
        "fdc3.showNotification": "show_notification",
        "fdc3.systemAlert": "system_alert",
    }

    def __init__(
        self,
        templates_dir: str = "src/fdc3/desktop_agent/templates",
        web_launcher: Optional[WebEndpointLauncher] = None,
    ):
        self.templates_dir = Path(templates_dir)
        self.system_app_id = "fdc3-desktop-agent"
        self.system_app_name = "FDC3 Desktop Agent"
        self.web_launcher = web_launcher or WebBrowserLauncher()

    async def _launch_web_url(
        self, url: str, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        return await self.web_launcher.launch(url, context=context)

    def is_system_intent(self, intent: str) -> bool:
        """Check if an intent is a system intent"""
        return intent in self.SYSTEM_INTENTS

    def get_system_app_identifier(self) -> AppIdentifier:
        """Get the system app identifier"""
        return AppIdentifier(
            appId=self.system_app_id, instanceId=None, desktopAgent=None
        )

    async def handle_system_intent(
        self,
        intent: str,
        context: Optional[Dict[str, Any]],
        target: Optional[AppIdentifier],
        sender: MessageSender,
        request_uuid: RequestUuid,
    ) -> Optional[BaseModel]:
        """Handle a system intent and return response"""

        handler_method = self.SYSTEM_INTENTS.get(intent)
        if not handler_method:
            return None

        try:
            # Call the appropriate handler method
            method = getattr(self, f"_handle_{handler_method}")
            success = await method(context, target)

            if success:
                # Create successful resolution
                resolution = IntentResolution(
                    source=self.get_system_app_identifier(), intent=intent
                )

                response = RaiseIntentResponse(
                    type="raiseIntentResponse",
                    payload=RaiseIntentResponsePayload(
                        intentResolution=resolution.model_dump()
                    ),
                    meta=AgentResponseMeta(requestUuid=request_uuid),
                )
                return response
            else:
                response = AgentResponse(
                    type="raiseIntentResponse",
                    payload=ErrorResponsePayload(error="IntentHandlingFailed"),
                    meta=AgentResponseMeta(requestUuid=request_uuid),
                )
                return response

        except Exception as e:
            logger.error(f"Failed to handle system intent {intent}: {e}")

            response = AgentResponse(
                type="raiseIntentResponse",
                payload=ErrorResponsePayload(error=f"IntentHandlingFailed: {repr(e)}"),
                meta=AgentResponseMeta(requestUuid=request_uuid),
            )
            return response

    async def _handle_open_app_directory(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Open app directory management interface"""
        try:
            # Open the app directory management page
            directory_url = "http://localhost:8000/app-directory"
            return await self._launch_web_url(directory_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open app directory: {e}")
            return False

    async def _handle_manage_apps(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Launch app management/configuration UI"""
        try:
            # Open the app management interface
            manage_url = "http://localhost:8000/manage-apps"
            return await self._launch_web_url(manage_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open app management: {e}")
            return False

    async def _handle_install_app(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Handle app installation from app directory"""
        # For now, just open the app directory with install mode
        try:
            install_url = "http://localhost:8000/app-directory?mode=install"
            return await self._launch_web_url(install_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open app installation: {e}")
            return False

    async def _handle_uninstall_app(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Remove apps from the system"""
        try:
            uninstall_url = "http://localhost:8000/manage-apps?mode=uninstall"
            return await self._launch_web_url(uninstall_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open app uninstallation: {e}")
            return False

    async def _handle_system_settings(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Open system configuration panel"""
        try:
            settings_url = "http://localhost:8000/system-settings"
            return await self._launch_web_url(settings_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open system settings: {e}")
            return False

    async def _handle_configure_channels(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Manage user/system channels"""
        try:
            channels_url = "http://localhost:8000/channels"
            return await self._launch_web_url(channels_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open channel configuration: {e}")
            return False

    async def _handle_system_diagnostics(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Run system health checks and diagnostics"""
        try:
            diagnostics_url = "http://localhost:8000/diagnostics"
            return await self._launch_web_url(diagnostics_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open diagnostics: {e}")
            return False

    async def _handle_create_channel(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Create new user channels"""
        try:
            create_channel_url = "http://localhost:8000/channels?mode=create"
            return await self._launch_web_url(create_channel_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open channel creation: {e}")
            return False

    async def _handle_delete_channel(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Remove user channels"""
        try:
            delete_channel_url = "http://localhost:8000/channels?mode=delete"
            return await self._launch_web_url(delete_channel_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open channel deletion: {e}")
            return False

    async def _handle_manage_channel(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Configure channel settings and membership"""
        try:
            manage_channel_url = "http://localhost:8000/channels?mode=manage"
            return await self._launch_web_url(manage_channel_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open channel management: {e}")
            return False

    async def _handle_resolve_intent(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Show intent resolver when multiple apps can handle an intent"""
        try:
            # Extract intent information from context
            intent_name = context.get("intent") if context else None
            resolve_url = "http://localhost:8000/resolve-intent"
            if intent_name:
                resolve_url += f"?intent={intent_name}"
            return await self._launch_web_url(resolve_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open intent resolver: {e}")
            return False

    async def _handle_open_url(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Launch system browser for URLs"""
        try:
            if context and "url" in context:
                url = context["url"]
                return await self._launch_web_url(url, context=context)
            else:
                logger.warning("No URL provided in context for fdc3.openUrl")
                return False
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")
            return False

    async def _handle_open_file(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Launch system file manager for local files"""
        try:
            if context and "filePath" in context:
                file_path = context["filePath"]
                # Use system default application for the file
                if os.name == "nt":  # Windows
                    os.startfile(file_path)
                else:  # Unix-like systems
                    subprocess.run(["xdg-open", file_path])
                return True
            else:
                logger.warning("No filePath provided in context for fdc3.openFile")
                return False
        except Exception as e:
            logger.error(f"Failed to open file: {e}")
            return False

    async def _handle_system_search(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """System-wide search functionality"""
        try:
            search_url = "http://localhost:8000/search"
            if context and "query" in context:
                search_url += f"?q={context['query']}"
            return await self._launch_web_url(search_url, context=context)
        except Exception as e:
            logger.error(f"Failed to open system search: {e}")
            return False

    async def _handle_show_notification(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Display system notifications"""
        try:
            # For now, just log the notification - in a real implementation,
            # this would integrate with system notification APIs
            if context:
                title = context.get("title", "FDC3 Notification")
                body = context.get("body", "")
                logger.info(f"System notification: {title} - {body}")
            return True
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")
            return False

    async def _handle_system_alert(
        self, context: Optional[Dict[str, Any]], target: Optional[AppIdentifier]
    ) -> bool:
        """Show system alerts and confirmations"""
        try:
            alert_url = "http://localhost:8000/alert"
            if context:
                alert_url += f"?message={context.get('message', '')}"
            return await self._launch_web_url(alert_url, context=context)
        except Exception as e:
            logger.error(f"Failed to show system alert: {e}")
            return False
