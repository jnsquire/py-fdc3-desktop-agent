# Constants and system metadata for the FDC3 Desktop Agent server

from ..storage.interfaces import AppMetadata
from ..version import __version__

# System app metadata (constant)
SYSTEM_APP_METADATA = AppMetadata(
    app_id="fdc3-desktop-agent",
    name="FDC3 Desktop Agent",
    version=__version__,
    description="Built-in system app for FDC3 Desktop Agent functionality",
    intents=[
        # App Directory Management
        "fdc3.openAppDirectory",
        "fdc3.manageApps",
        "fdc3.installApp",
        "fdc3.uninstallApp",
        # System Configuration
        "fdc3.systemSettings",
        "fdc3.configureChannels",
        "fdc3.systemDiagnostics",
        # Channel Management
        "fdc3.createChannel",
        "fdc3.deleteChannel",
        "fdc3.manageChannel",
        # Built-in System Apps
        "fdc3.resolveIntent",
        # System Browser/File Manager
        "fdc3.openUrl",
        "fdc3.openFile",
        "fdc3.systemSearch",
        # System Notifications
        "fdc3.showNotification",
        "fdc3.systemAlert",
    ],
)
