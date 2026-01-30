import pytest

from typing import cast

from fdc3.desktop_agent.handlers.dacp import DACPHandler
from fdc3.desktop_agent.handlers.dacp import PrivateChannelEventListenerTypes
from fdc3.desktop_agent.handlers.connection_manager import WebSocketConnectionManager
from fdc3.desktop_agent.launcher.interfaces import ProcessLauncher, LaunchResult
from fdc3.desktop_agent.storage import (
    Storage,
    AppDirectoryRepository,
    LaunchConfigRepository,
)
from fdc3.models.identifiers import AppIdentifier


class DummyStorage(Storage):
    class Apps(AppDirectoryRepository):
        async def list_apps(self):
            return []

        async def get_app_metadata(self, app_id):
            return None

        async def add_app(self, metadata):
            return None

        async def remove_app(self, app_id):
            return None

    class LaunchConfigs(LaunchConfigRepository):
        async def get_launch_config(self, app_id):
            return None

        async def set_launch_config(self, config):
            return None

        async def remove_launch_config(self, app_id):
            return None

        async def list_launch_configs(self):
            return []

    def __init__(self):
        self._apps = DummyStorage.Apps()
        self._launch_configs = DummyStorage.LaunchConfigs()

    @property
    def apps(self):
        return self._apps

    @property
    def launch_configs(self):
        return self._launch_configs

    async def initialize(self):
        return None

    async def close(self):
        return None


class DummyLauncher(ProcessLauncher):
    async def launch_app(self, *args, **kwargs):
        return LaunchResult(success=False)

    async def terminate_app(self, instance_uuid: str):
        return True

    async def is_app_running(self, instance_uuid: str):
        return False

    async def wait_for_app_exit(self, instance_uuid: str, timeout=None):
        return True

    async def stop(self):
        return None


class DummyConnMgr:
    def __init__(self):
        self.sent = []

    async def send_to_instance(self, instance_uuid, payload):
        self.sent.append((instance_uuid, payload))


class DummyCore:
    class ChannelManager:
        def get_remote_private_channel_listeners(self, channel_id):
            return ["da-1"]

        def get_channel(self, channel_id):
            return type(
                "C",
                (),
                {"id": channel_id, "type": "private", "members": []},
            )()

        def list_channels(self):
            return []

    def __init__(self):
        self.app_registry = type("R", (), {"get_instance": lambda *_: None})()
        self.channel_manager = DummyCore.ChannelManager()
        self.listener_store = type("LS", (), {"get_event_listeners": lambda *_: []})()


@pytest.mark.asyncio
async def test_session_identity_and_source_app_identifier_defaults():
    dacp = DACPHandler(
        DummyStorage(),
        cast(ProcessLauncher, DummyLauncher()),
        cast(WebSocketConnectionManager, DummyConnMgr()),
        None,
        core=DummyCore(),
    )

    # No session -> default identity
    ident = dacp._get_session_identity(None, None)
    assert getattr(ident, "appId", None) is None or getattr(ident, "appId", None) == ""

    # source app identifier falls back to unknown when no session
    src = dacp._get_source_app_identifier(None, None)
    assert isinstance(src, AppIdentifier)
    assert src.appId == "unknown"


@pytest.mark.asyncio
async def test_bridge_source_from_instance_uuid_with_missing_instance():
    core = DummyCore()
    dacp = DACPHandler(
        DummyStorage(),
        cast(ProcessLauncher, DummyLauncher()),
        cast(WebSocketConnectionManager, DummyConnMgr()),
        None,
        core=core,
    )
    # instance lookup returns None -> should return desktop-agent identifier
    a = dacp._bridge_source_from_instance_uuid("nonexistent")
    assert a.appId == "fdc3-desktop-agent"


@pytest.mark.asyncio
async def test_bridge_private_channel_listener_update_no_bridge():
    core = DummyCore()
    conn = DummyConnMgr()
    dacp = DACPHandler(
        DummyStorage(),
        cast(ProcessLauncher, DummyLauncher()),
        cast(WebSocketConnectionManager, conn),
        None,
        core=core,
    )

    # bridge_client is None -> function should return without exception
    await dacp._bridge_private_channel_listener_update(
        channel_id="ch1",
        event_type=PrivateChannelEventListenerTypes.onDisconnect,
        source_identity=AppIdentifier(appId="app1", instanceId=None, desktopAgent=None),
        added=True,
    )
