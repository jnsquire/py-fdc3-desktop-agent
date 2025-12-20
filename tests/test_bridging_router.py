from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from fdc3.desktop_agent.api import IntentResolution, OpenError, ResolveError
from fdc3.desktop_agent.bridging.router import BridgeRequestRouter
from fdc3.models.identifiers import AppIdentifier


@pytest.fixture
def connection_manager():
    return SimpleNamespace(send_to_instance=AsyncMock())


@pytest.fixture
def router_factory(connection_manager):
    def _make_router(
        *,
        storage=None,
        launcher=None,
        core=None,
        local_name: str | None = "local-da",
    ) -> BridgeRequestRouter:
        return BridgeRequestRouter(
            storage=storage or SimpleNamespace(),
            launcher=launcher or SimpleNamespace(),
            connection_manager=connection_manager,
            core_services=core or SimpleNamespace(),
            local_desktop_agent_name=local_name,
        )

    return _make_router


@pytest.mark.asyncio
async def test_bridge_router_broadcast_request_fanouts_and_returns_none(
    router_factory, connection_manager
):
    core = SimpleNamespace(
        context_router=SimpleNamespace(
            broadcast_context=Mock(return_value=["i-1", "i-2"])
        )
    )

    router = router_factory(core=core)

    resp = await router.handle(
        {
            "type": "broadcastRequest",
            "payload": {
                "context": {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}}
            },
            "meta": {"requestUuid": "r-1"},
        }
    )

    assert resp is None
    core.context_router.broadcast_context.assert_called_once()
    assert connection_manager.send_to_instance.await_count == 2


@pytest.mark.asyncio
async def test_bridge_router_open_request_success_builds_open_response(router_factory):
    apps = SimpleNamespace(
        get_app_metadata=AsyncMock(return_value=SimpleNamespace(app_id="app-1"))
    )
    launch_configs = SimpleNamespace(
        get_launch_config=AsyncMock(return_value=SimpleNamespace(app_id="app-1"))
    )
    storage = SimpleNamespace(apps=apps, launch_configs=launch_configs)

    launcher = SimpleNamespace(
        launch_app=AsyncMock(
            return_value=SimpleNamespace(success=True, instance_id="inst-1")
        )
    )

    router = router_factory(storage=storage, launcher=launcher)

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
    apps = SimpleNamespace(get_app_metadata=AsyncMock(return_value=None))
    launch_configs = SimpleNamespace(get_launch_config=AsyncMock(return_value=None))
    storage = SimpleNamespace(apps=apps, launch_configs=launch_configs)

    launcher = SimpleNamespace(launch_app=AsyncMock())

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

    core = SimpleNamespace(
        intent_resolver=SimpleNamespace(
            resolve_intent=Mock(return_value=resolution),
            deliver_intent_event=Mock(return_value=["inst-123"]),
        )
    )

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
    apps = SimpleNamespace(
        get_app_metadata=AsyncMock(
            return_value=SimpleNamespace(
                app_id="app-1",
                name="App One",
                version="1.2.3",
                description="desc",
                icons=[{"src": "https://example/icon.png"}],
            )
        )
    )
    storage = SimpleNamespace(apps=apps)

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
    apps = SimpleNamespace(get_app_metadata=AsyncMock(return_value=None))
    storage = SimpleNamespace(apps=apps)

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
    core = SimpleNamespace(
        app_registry=SimpleNamespace(
            get_connected_instances_for_app=Mock(
                return_value=[
                    SimpleNamespace(app_id="app-1", instance_id="i-1"),
                    SimpleNamespace(app_id="app-1", instance_id="i-2"),
                ]
            )
        )
    )

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
    core = SimpleNamespace(
        app_registry=SimpleNamespace(get_connected_instances_for_app=Mock())
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
    apps = SimpleNamespace(list_apps=AsyncMock(return_value=[]))
    storage = SimpleNamespace(apps=apps)

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
    apps = SimpleNamespace(
        list_apps=AsyncMock(
            return_value=[
                SimpleNamespace(
                    app_id="a1",
                    name="A1",
                    version="1",
                    description=None,
                    icons=None,
                    intents=["Other"],
                )
            ]
        )
    )
    storage = SimpleNamespace(apps=apps)

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
    apps = SimpleNamespace(
        list_apps=AsyncMock(
            return_value=[
                SimpleNamespace(
                    app_id="a1",
                    name="A1",
                    version="1",
                    description="d1",
                    icons=[{"src": "x"}],
                    intents=["ViewChart"],
                ),
                SimpleNamespace(
                    app_id="a2",
                    name="A2",
                    version="2",
                    description="d2",
                    icons=None,
                    intents=["Other", "ViewChart"],
                ),
            ]
        )
    )
    storage = SimpleNamespace(apps=apps)

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
