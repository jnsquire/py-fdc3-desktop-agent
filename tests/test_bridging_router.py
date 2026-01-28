from dataclasses import dataclass, field
from unittest.mock import AsyncMock, Mock

import pytest

from fdc3.desktop_agent.api import IntentResolution, OpenError, ResolveError
from fdc3.desktop_agent.bridging.router import BridgeRequestRouter
from fdc3.desktop_agent.core.channel_manager import ChannelManager
from fdc3.desktop_agent.core.listener_store import ListenerStore
from fdc3.models.primitives import ListenerUuid
from fdc3.models.identifiers import AppIdentifier
from fdc3.desktop_agent.storage import AppMetadata


@dataclass
class ConnectionManagerStub:
    send_to_instance: AsyncMock = field(default_factory=AsyncMock)


@dataclass
class LaunchConfigMeta:
    app_id: str


@dataclass
class LaunchResultStub:
    success: bool
    instance_id: str | None = None
    instance_uuid: str | None = None


@dataclass
class AppInstance:
    app_id: str
    instance_id: str
    instance_uuid: str | None = None


@dataclass
class AppsRepoStub:
    get_app_metadata: AsyncMock
    list_apps: AsyncMock


@dataclass
class LaunchConfigsRepoStub:
    get_launch_config: AsyncMock


@dataclass
class StorageStub:
    apps: AppsRepoStub
    launch_configs: LaunchConfigsRepoStub


@dataclass
class LauncherStub:
    launch_app: AsyncMock


@dataclass
class ContextRouterStub:
    broadcast_context: Mock = field(default_factory=lambda: Mock(return_value=[]))


@dataclass
class IntentResolverStub:
    resolve_intent: Mock = field(default_factory=Mock)
    deliver_intent_event: Mock = field(default_factory=Mock)


@dataclass
class AppRegistryStub:
    get_connected_instances_for_app: Mock = field(default_factory=Mock)
    get_instances_for_app: Mock = field(default_factory=Mock)
    register_pending_instance: Mock = field(default_factory=Mock)
    wait_for_instance_connection: AsyncMock = field(
        default_factory=lambda: AsyncMock(return_value=True)
    )
    unregister_instance: Mock = field(default_factory=Mock)


@dataclass
class CoreServicesStub:
    context_router: ContextRouterStub = field(default_factory=ContextRouterStub)
    intent_resolver: IntentResolverStub = field(default_factory=IntentResolverStub)
    app_registry: AppRegistryStub = field(default_factory=AppRegistryStub)
    listener_store: ListenerStore | None = None
    channel_manager: ChannelManager | None = None


@pytest.fixture
def connection_manager():
    return ConnectionManagerStub()


@pytest.fixture
def router_factory(connection_manager):
    def _make_router(
        *,
        storage=None,
        launcher=None,
        core=None,
        local_name: str | None = "local-da",
        dacp_handler=None,
    ) -> BridgeRequestRouter:
        from fdc3.desktop_agent.handlers.dacp import DACPHandler

        storage = storage or make_storage()
        launcher = launcher or make_launcher()
        connection_manager_inst = connection_manager
        core_services_inst = core or CoreServicesStub()

        if dacp_handler is None:
            dacp_handler = DACPHandler(
                storage=storage,
                launcher=launcher,
                connection_manager=connection_manager_inst,
                core=core_services_inst,
            )

        return BridgeRequestRouter(
            storage=storage,
            launcher=launcher,
            connection_manager=connection_manager_inst,
            core_services=core_services_inst,
            local_desktop_agent_name=local_name,
            dacp_handler=dacp_handler,
        )

    return _make_router


def make_apps(get_app_metadata=None, list_apps=None):
    return AppsRepoStub(
        get_app_metadata=AsyncMock(return_value=get_app_metadata)
        if get_app_metadata is not None
        else AsyncMock(return_value=None),
        list_apps=AsyncMock(return_value=list_apps or []),
    )


def make_launch_configs(get_launch_config=None):
    return LaunchConfigsRepoStub(
        get_launch_config=AsyncMock(return_value=get_launch_config)
        if get_launch_config is not None
        else AsyncMock(return_value=None)
    )


def make_storage(apps=None, launch_configs=None):
    return StorageStub(
        apps=apps or make_apps(),
        launch_configs=launch_configs or make_launch_configs(),
    )


def make_launcher(launch_app=None):
    return LauncherStub(
        launch_app=AsyncMock(return_value=launch_app)
        if launch_app is not None
        else AsyncMock()
    )


def make_core(context_router=None, intent_resolver=None, app_registry=None):
    return CoreServicesStub(
        context_router=context_router or ContextRouterStub(),
        intent_resolver=intent_resolver or IntentResolverStub(),
        app_registry=app_registry or AppRegistryStub(),
    )


@pytest.mark.asyncio
async def test_bridge_router_fdc3_event_delivery_targets_instance(
    router_factory, connection_manager
):
    app_registry = AppRegistryStub(
        get_connected_instances_for_app=Mock(
            return_value=[AppInstance("app-1", "inst-1", "uuid-1")]
        )
    )
    core = make_core(app_registry=app_registry)
    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "fdc3Event",
            "payload": {
                "event": {
                    "type": "USER_CHANNEL_CHANGED",
                    "details": {"currentChannelId": "user:red"},
                }
            },
            "meta": {
                "requestUuid": "r-event",
                "destination": {"appId": "app-1", "instanceId": "inst-1"},
            },
        }
    )

    assert resp is None
    connection_manager.send_to_instance.assert_awaited_once()


@pytest.mark.asyncio
async def test_bridge_router_broadcast_request_fanouts_and_returns_none(
    router_factory, connection_manager
):
    core = CoreServicesStub(
        context_router=ContextRouterStub(
            broadcast_context=Mock(return_value=["i-1", "i-2"])
        )
    )

    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "broadcastRequest",
            "payload": {
                "context": {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}},
                "channelId": "user:red",
            },
            "meta": {"requestUuid": "r-1"},
        }
    )

    assert resp is None
    core.context_router.broadcast_context.assert_called_once_with(
        {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}},
        source_instance_uuid="",
        channel_id="user:red",
    )
    assert connection_manager.send_to_instance.await_count == 2


@pytest.mark.asyncio
async def test_bridge_router_private_channel_event_delivery(
    router_factory, connection_manager
):
    listener_store = ListenerStore()
    listener_store.add_event_listener(
        listener_uuid=ListenerUuid(root="l-1"),
        instance_uuid="inst-1",
        event_type="onDisconnect",
        channel_id="private:abc",
    )
    core = CoreServicesStub(
        context_router=ContextRouterStub(),
        intent_resolver=IntentResolverStub(),
        app_registry=AppRegistryStub(),
        listener_store=listener_store,
        channel_manager=ChannelManager(),
    )

    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "privateChannelEvent",
            "payload": {
                "channelId": "private:abc",
                "eventType": "onDisconnect",
                "details": {"initiatorInstanceUuid": "inst-2"},
            },
            "meta": {"requestUuid": "r-priv-1"},
        }
    )

    assert resp is None
    connection_manager.send_to_instance.assert_awaited_once()


@pytest.mark.asyncio
async def test_bridge_router_private_channel_event_listener_updates_remote_tracking(
    router_factory,
):
    channel_manager = ChannelManager()
    core = CoreServicesStub(
        context_router=ContextRouterStub(),
        intent_resolver=IntentResolverStub(),
        app_registry=AppRegistryStub(),
        listener_store=ListenerStore(),
        channel_manager=channel_manager,
    )

    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "privateChannelEventListenerAdded",
            "payload": {"channelId": "private:abc"},
            "meta": {
                "requestUuid": "r-priv-2",
                "source": {"desktopAgent": "remote-da", "appId": "app-1"},
            },
        }
    )

    assert resp is None

    assert "remote-da" in channel_manager.get_remote_private_channel_listeners(
        "private:abc"
    )

    resp = await router.handle(
        {
            "type": "privateChannelEventListenerRemoved",
            "payload": {"channelId": "private:abc"},
            "meta": {
                "requestUuid": "r-priv-3",
                "source": {"desktopAgent": "remote-da", "appId": "app-1"},
            },
        }
    )

    assert resp is None

    assert "remote-da" not in channel_manager.get_remote_private_channel_listeners(
        "private:abc"
    )


@pytest.mark.asyncio
async def test_bridge_router_open_request_success_builds_open_response(router_factory):
    apps = make_apps(get_app_metadata=AppMetadata(app_id="app-1", name="App 1"))
    launch_configs = make_launch_configs(
        get_launch_config=LaunchConfigMeta(app_id="app-1")
    )
    storage = make_storage(apps=apps, launch_configs=launch_configs)

    launcher = make_launcher(
        launch_app=LaunchResultStub(
            success=True, instance_id="inst-1", instance_uuid="uuid-1"
        )
    )
    app_registry = AppRegistryStub(
        register_pending_instance=Mock(),
        wait_for_instance_connection=AsyncMock(return_value=True),
        unregister_instance=Mock(),
    )
    core = make_core(app_registry=app_registry)

    router = router_factory(storage=storage, launcher=launcher, core=core)

    resp = await router.handle(
        {
            "type": "openRequest",
            "payload": {
                "app": {"appId": "app-1"},
                "context": {"type": "fdc3.instrument"},
            },
            "meta": {"requestUuid": "r-open"},
        }
    )

    assert resp is not None
    assert resp["type"] == "openResponse"
    assert resp["meta"]["requestUuid"] == "r-open"
    assert resp["payload"]["appIdentifier"]["appId"] == "app-1"
    assert resp["payload"]["appIdentifier"]["instanceId"] == "inst-1"
    assert resp["payload"]["appIdentifier"]["desktopAgent"] == "local-da"


@pytest.mark.asyncio
async def test_bridge_router_open_request_app_not_found_returns_error_payload(
    router_factory,
):
    apps = make_apps(get_app_metadata=None)
    launch_configs = make_launch_configs(get_launch_config=None)
    storage = make_storage(apps=apps, launch_configs=launch_configs)

    launcher = make_launcher()

    router = router_factory(storage=storage, launcher=launcher)

    resp = await router.handle(
        {
            "type": "openRequest",
            "payload": {"app": {"appId": "missing"}},
            "meta": {"requestUuid": "r-open"},
        }
    )

    assert resp is not None
    assert resp["type"] == "openResponse"
    assert resp["payload"]["error"] == "AppNotFound"


@pytest.mark.asyncio
async def test_bridge_router_raise_intent_request_delivers_intent_event_and_returns_resolution(
    router_factory, connection_manager
):
    resolution = IntentResolution(
        source=AppIdentifier(appId="target", instanceId="target-1"),
        intent="ViewChart",
    )

    intent_resolver = IntentResolverStub(
        resolve_intent=Mock(return_value=resolution),
        deliver_intent_event=Mock(return_value=["inst-123"]),
    )
    core = make_core(intent_resolver=intent_resolver)

    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "raiseIntentRequest",
            "payload": {"intent": "ViewChart", "context": {"type": "fdc3.instrument"}},
            "meta": {
                "requestUuid": "r-intent",
                "source": {"appId": "caller", "instanceId": "c1"},
            },
        }
    )

    assert resp is not None
    assert resp["type"] == "raiseIntentResponse"
    assert resp["meta"]["requestUuid"] == "r-intent"
    assert resp["payload"]["intentResolution"]["intent"] == "ViewChart"
    assert connection_manager.send_to_instance.await_count == 1


@pytest.mark.asyncio
async def test_bridge_router_get_app_metadata_request_success_returns_metadata_payload(
    router_factory,
):
    apps = make_apps(
        get_app_metadata=AppMetadata(
            app_id="app-1",
            name="App One",
            version="1.2.3",
            description="desc",
            icons=[{"src": "https://example/icon.png"}],
        )
    )
    storage = make_storage(apps=apps)

    router = router_factory(storage=storage)

    resp = await router.handle(
        {
            "type": "getAppMetadataRequest",
            "payload": {"app": {"appId": "app-1"}},
            "meta": {"requestUuid": "r-meta"},
        }
    )

    assert resp is not None
    assert resp["type"] == "getAppMetadataResponse"
    assert resp["meta"]["requestUuid"] == "r-meta"
    assert resp["payload"]["appMetadata"]["appId"] == "app-1"
    assert resp["payload"]["appMetadata"]["name"] == "App One"
    assert resp["payload"]["appMetadata"]["version"] == "1.2.3"
    assert resp["payload"]["appMetadata"]["description"] == "desc"
    assert resp["payload"]["appMetadata"]["icons"] == [
        {"src": "https://example/icon.png"}
    ]
    assert resp["payload"]["appMetadata"]["desktopAgent"] == "local-da"


@pytest.mark.asyncio
async def test_bridge_router_get_app_metadata_request_missing_or_unknown_returns_app_not_found_error(
    router_factory,
):
    apps = AppsRepoStub(
        get_app_metadata=AsyncMock(return_value=None),
        list_apps=AsyncMock(return_value=[]),
    )
    storage = StorageStub(apps=apps, launch_configs=make_launch_configs())

    router = router_factory(storage=storage)

    resp_missing = await router.handle(
        {
            "type": "getAppMetadataRequest",
            "payload": {"app": {}},
            "meta": {"requestUuid": "r-missing"},
        }
    )
    assert resp_missing is not None
    assert resp_missing["type"] == "getAppMetadataResponse"
    assert resp_missing["payload"]["error"] == OpenError.AppNotFound.value

    resp_unknown = await router.handle(
        {
            "type": "getAppMetadataRequest",
            "payload": {"app": {"appId": "does-not-exist"}},
            "meta": {"requestUuid": "r-unknown"},
        }
    )
    assert resp_unknown is not None
    assert resp_unknown["type"] == "getAppMetadataResponse"
    assert resp_unknown["payload"]["error"] == OpenError.AppNotFound.value


@pytest.mark.asyncio
async def test_bridge_router_find_instances_request_returns_identifiers_for_connected_instances(
    router_factory,
):
    app_registry = AppRegistryStub(
        get_connected_instances_for_app=Mock(
            return_value=[
                AppInstance(app_id="app-1", instance_id="i-1"),
                AppInstance(app_id="app-1", instance_id="i-2"),
            ]
        ),
        get_instances_for_app=Mock(
            return_value=[
                AppInstance(app_id="app-1", instance_id="i-1"),
                AppInstance(app_id="app-1", instance_id="i-2"),
            ]
        ),
    )
    core = make_core(app_registry=app_registry)

    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "findInstancesRequest",
            "payload": {"app": {"appId": "app-1"}},
            "meta": {"requestUuid": "r-find"},
        }
    )

    assert resp is not None
    assert resp["type"] == "findInstancesResponse"
    assert resp["meta"]["requestUuid"] == "r-find"
    assert resp["payload"]["appIdentifiers"] == [
        {"appId": "app-1", "instanceId": "i-1", "desktopAgent": "local-da"},
        {"appId": "app-1", "instanceId": "i-2", "desktopAgent": "local-da"},
    ]
    core.app_registry.get_connected_instances_for_app.assert_called_once_with("app-1")


@pytest.mark.asyncio
async def test_bridge_router_find_instances_request_missing_app_id_returns_empty_list(
    router_factory,
):
    core = CoreServicesStub(
        app_registry=AppRegistryStub(get_connected_instances_for_app=Mock())
    )

    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "findInstancesRequest",
            "payload": {"app": {}},
            "meta": {"requestUuid": "r-find"},
        }
    )

    assert resp is not None
    assert resp["type"] == "findInstancesResponse"
    assert resp["payload"]["appIdentifiers"] == []
    core.app_registry.get_connected_instances_for_app.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_router_find_intent_request_returns_error_when_missing_intent(
    router_factory,
):
    apps = make_apps(list_apps=[])
    storage = make_storage(apps=apps)

    router = router_factory(storage=storage)

    resp = await router.handle(
        {
            "type": "findIntentRequest",
            "payload": {},
            "meta": {"requestUuid": "r-intent"},
        }
    )

    assert resp is not None
    assert resp["type"] == "findIntentResponse"
    assert resp["payload"]["error"] == ResolveError.NoAppsFound.value
    apps.list_apps.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_router_find_intent_request_returns_error_when_no_matching_apps(
    router_factory,
):
    apps = make_apps(
        list_apps=[
            AppMetadata(
                app_id="a1",
                name="A1",
                version="1",
                description="",
                icons=None,
                intents=["Other"],
            )
        ]
    )
    storage = make_storage(apps=apps)

    router = router_factory(storage=storage)

    resp = await router.handle(
        {
            "type": "findIntentRequest",
            "payload": {"intent": "ViewChart"},
            "meta": {"requestUuid": "r-intent"},
        }
    )

    assert resp is not None
    assert resp["type"] == "findIntentResponse"
    assert resp["payload"]["error"] == ResolveError.NoAppsFound.value


@pytest.mark.asyncio
async def test_bridge_router_find_intent_request_returns_app_intent_for_matches(
    router_factory,
):
    apps = make_apps(
        list_apps=[
            AppMetadata(
                app_id="a1",
                name="A1",
                version="1",
                description="d1",
                icons=[{"src": "x"}],
                intents=["ViewChart"],
            ),
            AppMetadata(
                app_id="a2",
                name="A2",
                version="2",
                description="d2",
                icons=None,
                intents=["Other", "ViewChart"],
            ),
        ]
    )
    storage = make_storage(apps=apps)

    router = router_factory(storage=storage)

    resp = await router.handle(
        {
            "type": "findIntentRequest",
            "payload": {"intent": "ViewChart"},
            "meta": {"requestUuid": "r-intent"},
        }
    )

    assert resp is not None
    assert resp["type"] == "findIntentResponse"
    assert resp["meta"]["requestUuid"] == "r-intent"
    assert resp["payload"]["appIntent"]["intent"] == {"name": "ViewChart"}
    apps_payload = resp["payload"]["appIntent"]["apps"]
    assert {a["appId"] for a in apps_payload} == {"a1", "a2"}
    assert all(a["desktopAgent"] == "local-da" for a in apps_payload)


@pytest.mark.asyncio
async def test_bridge_router_find_intents_by_context_request_returns_empty_list(
    router_factory,
):
    router = router_factory()

    resp = await router.handle(
        {
            "type": "findIntentsByContextRequest",
            "payload": {"context": {"type": "fdc3.instrument"}},
            "meta": {"requestUuid": "r-c"},
        }
    )

    assert resp is not None
    assert resp["type"] == "findIntentsByContextResponse"
    assert resp["payload"] == {"appIntents": []}


@pytest.mark.asyncio
async def test_bridge_router_unknown_or_malformed_requests_return_malformed_message_error(
    router_factory,
):
    router = router_factory()

    resp_unknown = await router.handle(
        {
            "type": "someWeirdRequest",
            "payload": {},
            "meta": {"requestUuid": "r-x"},
        }
    )
    assert resp_unknown is not None
    assert resp_unknown["type"] == "someWeirdResponse"
    assert resp_unknown["payload"]["error"] == "MalformedMessage"

    resp_no_type = await router.handle({"payload": {}, "meta": {"requestUuid": "r-y"}})
    assert resp_no_type is not None
    assert resp_no_type["type"] == "unknownResponse"
    assert resp_no_type["payload"]["error"] == "MalformedMessage"


@pytest.mark.asyncio
async def test_bridge_router_returns_none_when_request_uuid_missing(router_factory):
    router = router_factory()

    resp = await router.handle(
        {"type": "findInstancesRequest", "payload": {}, "meta": {}}
    )
    assert resp is None
