from typing import cast

import pytest

from fdc3.desktop_agent.handlers.dacp import DACPHandler
from fdc3.desktop_agent.launcher.interfaces import ProcessLauncher, LaunchResult
from fdc3.desktop_agent.storage import (
    Storage,
    AppDirectoryRepository,
    LaunchConfigRepository,
)
from fdc3.models.dacp.dacp import Fdc3Context


class Meta:
    def __init__(self, app_id, intents, result_type=None, name=None):
        self.app_id = app_id
        self.intents = intents
        self.resultType = result_type
        self.name = name


class DummyStorage(Storage):
    class Apps(AppDirectoryRepository):
        def __init__(self, listed, meta_by_id):
            self._listed = listed
            self._meta_by_id = meta_by_id

        async def list_apps(self):
            return self._listed

        async def get_app_metadata(self, app_id):
            return self._meta_by_id.get(app_id)

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

    def __init__(self, listed, meta_by_id):
        self._apps = DummyStorage.Apps(listed, meta_by_id)
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
    async def send_to_instance(self, instance_uuid, payload):
        return None


class DummyListener:
    def __init__(self, intent, instance_uuid):
        self.intent = intent
        self.instance_uuid = instance_uuid


class DummyCore:
    def __init__(self, listener_intent=None, listener_app_id=None):
        class AppRegistry:
            def __init__(self, app_id):
                self._app_id = app_id

            def get_instance(self, instance_uuid):
                if not self._app_id:
                    return None
                return type("Inst", (), {"app_id": self._app_id})()

        class ListenerStore:
            def __init__(self, listener):
                self.intent_listeners = {}
                if listener is not None:
                    self.intent_listeners["l1"] = listener

        self.app_registry = AppRegistry(listener_app_id)
        listener = DummyListener(listener_intent, "inst1") if listener_intent else None
        self.listener_store = ListenerStore(listener)


@pytest.mark.asyncio
async def test_collect_app_intents_filters_context_and_typed_result():
    meta1 = Meta(
        "app.contact",
        intents=[{"name": "ViewChart", "contexts": ["fdc3.contact"]}],
        result_type="channel<fdc3.contact>",
        name="Contacts",
    )
    meta2 = Meta(
        "app.instrument",
        intents=[{"name": "ViewChart", "contexts": ["fdc3.instrument"]}],
        result_type="channel<fdc3.instrument>",
        name="Instruments",
    )
    listed = [meta1, meta2]
    storage = DummyStorage(listed, {"app.contact": meta1, "app.instrument": meta2})
    dacp = DACPHandler(storage, DummyLauncher(), DummyConnMgr(), core=DummyCore())

    context = cast(Fdc3Context, {"type": "fdc3.contact"})
    app_intents, has_constraints = await dacp._collect_app_intents_by_context(
        context,
        result_type="channel",
        enforce_context=True,
    )

    assert has_constraints is True
    assert len(app_intents) == 1
    assert app_intents[0].intent.name == "ViewChart"
    apps = {app.appId for app in app_intents[0].apps}
    assert apps == {"app.contact"}


@pytest.mark.asyncio
async def test_collect_app_intents_includes_runtime_listener():
    meta1 = Meta(
        "app.contact",
        intents=[{"name": "ViewChart", "contexts": ["fdc3.contact"]}],
        result_type=None,
    )
    listed = [meta1]
    storage = DummyStorage(
        listed, {"app.contact": meta1, "app.runtime": Meta("app.runtime", intents=[])}
    )
    core = DummyCore(listener_intent="ViewChart", listener_app_id="app.runtime")
    dacp = DACPHandler(storage, DummyLauncher(), DummyConnMgr(), core=core)

    context = cast(Fdc3Context, {"type": "fdc3.contact"})
    app_intents, _ = await dacp._collect_app_intents_by_context(
        context,
        result_type=None,
        enforce_context=True,
    )

    assert len(app_intents) == 1
    apps = {app.appId for app in app_intents[0].apps}
    assert apps == {"app.contact", "app.runtime"}
