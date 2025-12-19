from fdc3.desktop_agent.handlers import WebSocketConnectionManager
from fdc3.desktop_agent.launcher import ProcessLauncher
from fdc3.desktop_agent.storage import Storage
import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from fdc3.desktop_agent.api import IntentResolution
from fdc3.desktop_agent.handlers.dacp import DACPHandler
from fdc3.desktop_agent.launcher.interfaces import LaunchResult
from fdc3.models.identifiers import AppIdentifier
from fdc3.models.primitives import ListenerUuid
from fdc3.models.dacp.dacp import ErrorResponsePayload


def _websocket() -> Any:
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _handler() -> tuple[DACPHandler, Any, Any, Any]:
    storage: Any = SimpleNamespace(
        apps=SimpleNamespace(get_app_metadata=AsyncMock(), list_apps=AsyncMock()),
        launch_configs=SimpleNamespace(get_launch_config=AsyncMock()),
    )
    launcher: Any = SimpleNamespace(launch_app=AsyncMock())
    connection_manager: Any = SimpleNamespace(send_to_instance=AsyncMock())

    handler = DACPHandler(
        storage=cast(Storage, storage),
        launcher=cast(ProcessLauncher, launcher),
        connection_manager=cast(WebSocketConnectionManager, connection_manager),
    )
    return handler, storage, launcher, connection_manager


def _wcp_sessions(instance_uuid: str = "src-uuid") -> tuple[str, dict]:
    session_id = "s1"
    return session_id, {session_id: {"identity": {"instanceUuid": instance_uuid}}}


class TestDACPHandlerParsingAndDispatch:
    @pytest.mark.asyncio
    async def test_handle_message_parse_error_missing_type(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        await handler.handle_message(
            message={}, session_id="s1", wcp_sessions={}, websocket=ws
        )

        ws.send_text.assert_called_once()
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["type"] == "errorResponse"

    @pytest.mark.asyncio
    async def test_handle_message_parse_error_known_type_uses_type_response(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        # Invalid open payload -> validation error in parser
        msg = {"type": "open", "payload": {}, "meta": {"requestUuid": "req-1"}}
        await handler.handle_message(
            message=msg, session_id="s1", wcp_sessions={}, websocket=ws
        )

        ws.send_text.assert_called_once()
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["type"] == "openResponse"
        assert payload["meta"]["requestUuid"] == "req-1"
        assert payload["payload"]["error"]

    @pytest.mark.asyncio
    async def test_handle_message_unknown_parsed_type_logs_warning(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        with (
            patch(
                "fdc3.desktop_agent.handlers.dacp.parse_message", return_value=object()
            ),
            patch("fdc3.desktop_agent.handlers.dacp.logger") as mock_logger,
        ):
            await handler.handle_message(
                message={"type": "something"},
                session_id="s1",
                wcp_sessions={},
                websocket=ws,
            )
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_handle_message_dispatches_known_types(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("src-uuid")

        # Patch internal handlers so we only validate dispatch wiring.
        with (
            patch.object(handler, "_handle_open", new_callable=AsyncMock) as h_open,
            patch.object(
                handler, "_handle_broadcast", new_callable=AsyncMock
            ) as h_broadcast,
            patch.object(
                handler, "_handle_add_context_listener", new_callable=AsyncMock
            ) as h_acl,
            patch.object(
                handler, "_handle_add_intent_listener", new_callable=AsyncMock
            ) as h_ail,
            patch.object(
                handler, "_handle_intent_listener_unsubscribe", new_callable=AsyncMock
            ) as h_ilu,
            patch.object(
                handler, "_handle_get_user_channels", new_callable=AsyncMock
            ) as h_gucs,
            patch.object(
                handler, "_handle_get_current_channel", new_callable=AsyncMock
            ) as h_gcc,
            patch.object(
                handler, "_handle_join_user_channel", new_callable=AsyncMock
            ) as h_juc,
            patch.object(
                handler, "_handle_leave_current_channel", new_callable=AsyncMock
            ) as h_lcc,
            patch.object(
                handler, "_handle_find_intent", new_callable=AsyncMock
            ) as h_fi,
            patch.object(
                handler, "_handle_find_intents_by_context", new_callable=AsyncMock
            ) as h_fibc,
            patch.object(
                handler, "_handle_find_instances", new_callable=AsyncMock
            ) as h_finst,
            patch.object(handler, "_handle_raise_intent", new_callable=AsyncMock),
            patch.object(
                handler, "_handle_raise_intent_for_context", new_callable=AsyncMock
            ) as h_rifc,
            patch.object(
                handler, "_handle_intent_result_request", new_callable=AsyncMock
            ) as h_irr,
            patch.object(
                handler, "_handle_raise_intent_result_response", new_callable=AsyncMock
            ) as h_rirr,
            patch.object(
                handler, "_handle_context_listener_unsubscribe", new_callable=AsyncMock
            ) as h_clu,
            patch.object(
                handler, "_handle_heartbeat_acknowledgment", new_callable=AsyncMock
            ) as h_hb,
            patch.object(
                handler, "_handle_external_intent_result", new_callable=AsyncMock
            ),
        ):
            # open
            await handler.handle_message(
                {
                    "type": "open",
                    "payload": {"app": {"appId": "a"}},
                    "meta": {"requestUuid": "r1"},
                },
                session_id,
                sessions,
                ws,
            )
            # broadcast
            await handler.handle_message(
                {
                    "type": "broadcast",
                    "payload": {"context": {"type": "t"}},
                    "meta": {"requestUuid": "r2"},
                },
                session_id,
                sessions,
                ws,
            )
            # addContextListener
            await handler.handle_message(
                {
                    "type": "addContextListener",
                    "payload": {},
                    "meta": {"requestUuid": "r3"},
                },
                session_id,
                sessions,
                ws,
            )
            # addIntentListener
            await handler.handle_message(
                {
                    "type": "addIntentListener",
                    "payload": {"intent": "ViewChart"},
                    "meta": {"requestUuid": "r4"},
                },
                session_id,
                sessions,
                ws,
            )

            # findIntent
            await handler.handle_message(
                {
                    "type": "findIntent",
                    "payload": {"intent": "ViewChart"},
                    "meta": {"requestUuid": "r4b"},
                },
                session_id,
                sessions,
                ws,
            )

            # findIntentsByContext
            await handler.handle_message(
                {
                    "type": "findIntentsByContext",
                    "payload": {"context": {"type": "fdc3.instrument"}},
                    "meta": {"requestUuid": "r4c"},
                },
                session_id,
                sessions,
                ws,
            )

            # findInstances
            await handler.handle_message(
                {
                    "type": "findInstances",
                    "payload": {"app": {"appId": "app-1"}},
                    "meta": {"requestUuid": "r4d"},
                },
                session_id,
                sessions,
                ws,
            )

            # getUserChannels
            await handler.handle_message(
                {
                    "type": "getUserChannels",
                    "payload": {},
                    "meta": {"requestUuid": "r4e"},
                },
                session_id,
                sessions,
                ws,
            )

            # getCurrentChannel
            await handler.handle_message(
                {
                    "type": "getCurrentChannel",
                    "payload": {},
                    "meta": {"requestUuid": "r4f"},
                },
                session_id,
                sessions,
                ws,
            )

            # joinUserChannel
            await handler.handle_message(
                {
                    "type": "joinUserChannel",
                    "payload": {"channelId": "user:red"},
                    "meta": {"requestUuid": "r4g"},
                },
                session_id,
                sessions,
                ws,
            )

            # leaveCurrentChannel
            await handler.handle_message(
                {
                    "type": "leaveCurrentChannel",
                    "payload": {},
                    "meta": {"requestUuid": "r4h"},
                },
                session_id,
                sessions,
                ws,
            )
            # intentListenerUnsubscribe
            await handler.handle_message(
                {
                    "type": "intentListenerUnsubscribe",
                    "payload": {"listenerUuid": "l1"},
                    "meta": {"requestUuid": "r5"},
                },
                session_id,
                sessions,
                ws,
            )
            # raiseIntentForContext
            await handler.handle_message(
                {
                    "type": "raiseIntentForContext",
                    "payload": {"context": {"type": "t"}},
                    "meta": {"requestUuid": "r6"},
                },
                session_id,
                sessions,
                ws,
            )
            # intentResultRequest
            await handler.handle_message(
                {
                    "type": "intentResultRequest",
                    "payload": {"intentResult": {"type": "t"}},
                    "meta": {"requestUuid": "r7"},
                },
                session_id,
                sessions,
                ws,
            )
            # raiseIntentResultResponse
            await handler.handle_message(
                {
                    "type": "raiseIntentResultResponse",
                    "payload": {},
                    "meta": {"requestUuid": "r8"},
                },
                session_id,
                sessions,
                ws,
            )
            # contextListenerUnsubscribe
            await handler.handle_message(
                {
                    "type": "contextListenerUnsubscribe",
                    "payload": {"listenerUuid": "l2"},
                    "meta": {"requestUuid": "r9"},
                },
                session_id,
                sessions,
                ws,
            )
            # heartbeatAcknowledgmentRequest
            await handler.handle_message(
                {
                    "type": "heartbeatAcknowledgmentRequest",
                    "payload": {"heartbeatEventUuid": "e1"},
                    "meta": {"requestUuid": "r10"},
                },
                session_id,
                sessions,
                ws,
            )
            # raiseIntent
            await handler.handle_message(
                {
                    "type": "raiseIntent",
                    "payload": {"intent": "ViewChart", "context": {"type": "t"}},
                    "meta": {"requestUuid": "r11"},
                },
                session_id,
                sessions,
                ws,
            )

            # external intentResult
            await handler.handle_message(
                {
                    "type": "intentResult",
                    "payload": {"request_uuid": "x", "error": "fail"},
                },
                session_id,
                sessions,
                ws,
            )

        assert h_open.await_count == 1
        assert h_broadcast.await_count == 1
        assert h_acl.await_count == 1
        assert h_ail.await_count == 1
        assert h_fi.await_count == 1
        assert h_finst.await_count == 1
        assert h_fibc.await_count == 1
        assert h_gucs.await_count == 1
        assert h_gcc.await_count == 1
        assert h_juc.await_count == 1
        assert h_lcc.await_count == 1
        assert h_ilu.await_count == 1
        assert h_rifc.await_count == 1
        assert h_irr.await_count == 1
        assert h_rirr.await_count == 1
        assert h_clu.await_count == 1
        assert h_hb.await_count == 1


class TestDACPHandlerUserChannels:
    @pytest.mark.asyncio
    async def test_get_user_channels_creates_defaults(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.desktop_agent.core import core_services

        core_services.channel_manager.channels.clear()
        core_services.channel_manager.instance_channels.clear()

        await handler.handle_message(
            {
                "type": "getUserChannels",
                "payload": {},
                "meta": {"requestUuid": "r1"},
            },
            session_id="s1",
            wcp_sessions={"s1": {"identity": {"instanceUuid": "i1"}}},
            websocket=ws,
        )

        ws.send_text.assert_called_once()
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["type"] == "getUserChannelsResponse"
        assert payload["meta"]["requestUuid"] == "r1"
        assert isinstance(payload["payload"]["channels"], list)
        assert any(c["id"] == "user:red" for c in payload["payload"]["channels"])

    @pytest.mark.asyncio
    async def test_join_get_current_leave_roundtrip(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("inst-1")

        from fdc3.desktop_agent.core import core_services

        core_services.channel_manager.channels.clear()
        core_services.channel_manager.instance_channels.clear()

        # Join by unprefixed id should map to user:<id>
        await handler.handle_message(
            {
                "type": "joinUserChannel",
                "payload": {"channelId": "red"},
                "meta": {"requestUuid": "r2"},
            },
            session_id,
            sessions,
            ws,
        )
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["type"] == "joinUserChannelResponse"
        assert payload["payload"]["channel"]["id"] == "user:red"

        ws.send_text.reset_mock()
        await handler.handle_message(
            {
                "type": "getCurrentChannel",
                "payload": {},
                "meta": {"requestUuid": "r3"},
            },
            session_id,
            sessions,
            ws,
        )
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["type"] == "getCurrentChannelResponse"
        assert payload["payload"]["channel"]["id"] == "user:red"

        ws.send_text.reset_mock()
        await handler.handle_message(
            {
                "type": "leaveCurrentChannel",
                "payload": {},
                "meta": {"requestUuid": "r4"},
            },
            session_id,
            sessions,
            ws,
        )
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["type"] == "leaveCurrentChannelResponse"

        ws.send_text.reset_mock()
        await handler.handle_message(
            {
                "type": "getCurrentChannel",
                "payload": {},
                "meta": {"requestUuid": "r5"},
            },
            session_id,
            sessions,
            ws,
        )
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["payload"]["channel"] is None

    @pytest.mark.asyncio
    async def test_join_user_channel_unknown_errors(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("inst-1")

        from fdc3.desktop_agent.core import core_services

        core_services.channel_manager.channels.clear()
        core_services.channel_manager.instance_channels.clear()

        # Ensure defaults exist then attempt a missing channel.
        await handler.handle_message(
            {
                "type": "getUserChannels",
                "payload": {},
                "meta": {"requestUuid": "seed"},
            },
            session_id,
            sessions,
            ws,
        )
        ws.send_text.reset_mock()

        await handler.handle_message(
            {
                "type": "joinUserChannel",
                "payload": {"channelId": "user:not-a-channel"},
                "meta": {"requestUuid": "r6"},
            },
            session_id,
            sessions,
            ws,
        )
        payload = json.loads(ws.send_text.call_args.args[0])
        assert payload["type"] == "joinUserChannelResponse"
        assert payload["payload"]["error"] == "NoChannelFound"


class TestDACPHandlerFindInstances:
    @pytest.mark.asyncio
    async def test_find_instances_empty(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import FindInstancesRequest

        req = FindInstancesRequest.model_validate(
            {
                "type": "findInstances",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = []
            await handler._handle_find_instances(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "findInstancesResponse"
            assert sent.payload.instances == []

    @pytest.mark.asyncio
    async def test_find_instances_filters_instance_id(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import FindInstancesRequest

        req = FindInstancesRequest.model_validate(
            {
                "type": "findInstances",
                "payload": {"app": {"appId": "app-1", "instanceId": "i2"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = [
                SimpleNamespace(instance_id="i1"),
                SimpleNamespace(instance_id="i2"),
            ]
            await handler._handle_find_instances(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "findInstancesResponse"
            assert len(sent.payload.instances) == 1
            assert sent.payload.instances[0].appId == "app-1"
            assert sent.payload.instances[0].instanceId == "i2"


class TestDACPHandlerFindIntent:
    @pytest.mark.asyncio
    async def test_find_intent_no_apps_found(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import FindIntentRequest

        req = FindIntentRequest.model_validate(
            {
                "type": "findIntent",
                "payload": {"intent": "ViewChart"},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.list_apps.return_value = []

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.get_intent_listeners_for_intent.return_value = []
            await handler._handle_find_intent(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "findIntentResponse"
            assert sent.payload.error == "NoAppsFound"

    @pytest.mark.asyncio
    async def test_find_intent_returns_app_intent_from_directory(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import FindIntentRequest
        from fdc3.desktop_agent.storage.interfaces import AppMetadata as StoredApp

        req = FindIntentRequest.model_validate(
            {
                "type": "findIntent",
                "payload": {"intent": "ViewChart"},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.list_apps.return_value = [
            StoredApp(app_id="app-1", name="A1", intents=["ViewChart"])
        ]

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.get_intent_listeners_for_intent.return_value = []
            await handler._handle_find_intent(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "findIntentResponse"
            assert sent.payload.appIntent.intent.name == "ViewChart"
            assert sent.payload.appIntent.apps[0].appId == "app-1"
            assert sent.payload.appIntent.apps[0].name == "A1"


class TestDACPHandlerFindIntentsByContext:
    @pytest.mark.asyncio
    async def test_find_intents_by_context_no_apps_found(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import FindIntentsByContextRequest

        req = FindIntentsByContextRequest.model_validate(
            {
                "type": "findIntentsByContext",
                "payload": {"context": {"type": "fdc3.instrument"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.list_apps.return_value = []

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.intent_listeners = {}
            await handler._handle_find_intents_by_context(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "findIntentsByContextResponse"
            assert sent.payload.error == "NoAppsFound"

    @pytest.mark.asyncio
    async def test_find_intents_by_context_returns_directory_intents(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import FindIntentsByContextRequest
        from fdc3.desktop_agent.storage.interfaces import AppMetadata as StoredApp

        req = FindIntentsByContextRequest.model_validate(
            {
                "type": "findIntentsByContext",
                "payload": {"context": {"type": "fdc3.instrument"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.list_apps.return_value = [
            StoredApp(app_id="app-1", name="A1", intents=["ViewChart", "ViewNews"])
        ]

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.intent_listeners = {}
            await handler._handle_find_intents_by_context(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "findIntentsByContextResponse"
            names = sorted([ai.intent.name for ai in sent.payload.appIntents])
            assert names == ["ViewChart", "ViewNews"]


class TestDACPHandlerSendModel:
    @pytest.mark.asyncio
    async def test_send_model_logs_on_send_error(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        ws.send_text.side_effect = RuntimeError("boom")

        model = SimpleNamespace(
            model_dump_json=lambda: "{}", __class__=SimpleNamespace(__name__="X")
        )

        with patch("fdc3.desktop_agent.handlers.dacp.logger") as mock_logger:
            await handler._send_model(ws, model)
            mock_logger.error.assert_called()


class TestDACPHandlerOpen:
    @pytest.mark.asyncio
    async def test_open_app_not_found(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "missing"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = None

        with patch.object(handler, "_send_model", new_callable=AsyncMock) as send:
            await handler._handle_open(req, ws)

            send.assert_called_once()
            sent = send.call_args.args[1]
            assert sent.type == "openResponse"
            assert sent.payload.error == "AppNotFound"

    @pytest.mark.asyncio
    async def test_open_reuses_existing_instance(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = {"id": "app-1"}

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = [
                SimpleNamespace(instance_id="inst-1", instance_uuid="uuid-1")
            ]

            await handler._handle_open(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "openResponse"

    @pytest.mark.asyncio
    async def test_open_reuses_requested_instance_id(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1", "instanceId": "inst-2"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = {"id": "app-1"}

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = [
                SimpleNamespace(instance_id="inst-2", instance_uuid="uuid-2")
            ]
            await handler._handle_open(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "openResponse"

    @pytest.mark.asyncio
    async def test_open_no_launch_config_returns_app_not_found(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = {"id": "app-1"}
        storage.launch_configs.get_launch_config.return_value = None

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = []
            await handler._handle_open(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "openResponse"
            assert sent.payload.error == "AppNotFound"

    @pytest.mark.asyncio
    async def test_open_exception_sends_app_launch_failed(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        async def boom(_: str):
            raise RuntimeError("boom")

        storage.apps.get_app_metadata.side_effect = boom

        with patch.object(handler, "_send_model", new_callable=AsyncMock) as send:
            await handler._handle_open(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "openResponse"
            assert sent.payload.error == "AppLaunchFailed"

    @pytest.mark.asyncio
    async def test_open_exception_and_send_fails_is_swallowed(self):
        handler, storage, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        async def boom(_: str):
            raise RuntimeError("boom")

        storage.apps.get_app_metadata.side_effect = boom

        with patch.object(handler, "_send_model", new_callable=AsyncMock) as send:
            send.side_effect = RuntimeError("send failed")
            await handler._handle_open(req, ws)

    @pytest.mark.asyncio
    async def test_open_launch_success_missing_instance_info_returns_error_on_launch(
        self,
    ):
        handler, storage, launcher, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = {"id": "app-1"}
        storage.launch_configs.get_launch_config.return_value = {"launch": True}
        launcher.launch_app.return_value = LaunchResult(
            success=True, instance_id=None, instance_uuid="uuid-1"
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = []
            await handler._handle_open(req, ws)

            sent = send.call_args.args[1]
            assert sent.type == "openResponse"
            assert sent.payload.error == "ErrorOnLaunch"

    @pytest.mark.asyncio
    async def test_open_launch_failure_returns_error_on_launch(self):
        handler, storage, launcher, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = {"id": "app-1"}
        storage.launch_configs.get_launch_config.return_value = {"launch": True}
        launcher.launch_app.return_value = LaunchResult(success=False, error="nope")

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = []
            await handler._handle_open(req, ws)

            sent = send.call_args.args[1]
            assert sent.type == "openResponse"
            assert sent.payload.error == "ErrorOnLaunch"

    @pytest.mark.asyncio
    async def test_open_launch_success_connected(self):
        handler, storage, launcher, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = {"id": "app-1"}
        storage.launch_configs.get_launch_config.return_value = {"launch": True}
        launcher.launch_app.return_value = LaunchResult(
            success=True, instance_id="inst-1", instance_uuid="uuid-1"
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = []
            cs.app_registry.wait_for_instance_connection = AsyncMock(return_value=True)

            await handler._handle_open(req, ws)

            cs.app_registry.register_pending_instance.assert_called_once()
            sent = send.call_args.args[1]
            assert sent.type == "openResponse"

    @pytest.mark.asyncio
    async def test_open_launch_success_timeout_unregisters(self):
        handler, storage, launcher, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import OpenRequest

        req = OpenRequest.model_validate(
            {
                "type": "open",
                "payload": {"app": {"appId": "app-1"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        storage.apps.get_app_metadata.return_value = {"id": "app-1"}
        storage.launch_configs.get_launch_config.return_value = {"launch": True}
        launcher.launch_app.return_value = LaunchResult(
            success=True, instance_id="inst-1", instance_uuid="uuid-1"
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.app_registry.get_instances_for_app.return_value = []
            cs.app_registry.wait_for_instance_connection = AsyncMock(return_value=False)

            await handler._handle_open(req, ws)

            cs.app_registry.unregister_instance.assert_called_once_with("uuid-1")
            sent = send.call_args.args[1]
            assert sent.type == "openResponse"
            assert sent.payload.error == "AppTimeout"


class TestDACPHandlerBroadcastAndListeners:
    @pytest.mark.asyncio
    async def test_broadcast_sends_events_to_targets(self):
        handler, _, _, connection_manager = _handler()
        session_id, sessions = _wcp_sessions("src-uuid")

        from fdc3.models.dacp.dacp import BroadcastRequest

        req = BroadcastRequest.model_validate(
            {
                "type": "broadcast",
                "payload": {"context": {"type": "fdc3.test"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs:
            cs.context_router.broadcast_context.return_value = ["t1", "t2"]

            await handler._handle_broadcast(req, session_id, sessions)

        assert connection_manager.send_to_instance.await_count == 2
        args0 = connection_manager.send_to_instance.await_args_list[0].args
        assert args0[0] in {"t1", "t2"}
        assert "broadcastEvent" in args0[1]

    @pytest.mark.asyncio
    async def test_add_context_listener_and_unsubscribe(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("src-uuid")

        from fdc3.models.dacp.dacp import (
            AddContextListenerRequest,
            ContextListenerUnsubscribeRequest,
        )

        add_req = AddContextListenerRequest.model_validate(
            {
                "type": "addContextListener",
                "payload": {"contextType": "fdc3.instrument"},
                "meta": {"requestUuid": "req-1"},
            }
        )

        listener_uuid = ListenerUuid(root="listener-1")

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.add_context_listener.return_value = SimpleNamespace(
                listener_uuid=listener_uuid
            )

            await handler._handle_add_context_listener(
                add_req, session_id, sessions, ws
            )
            sent = send.call_args.args[1]
            assert sent.payload.listenerUuid.root == "listener-1"

            unsub_req = ContextListenerUnsubscribeRequest.model_validate(
                {
                    "type": "contextListenerUnsubscribe",
                    "payload": {"listenerUuid": "listener-1"},
                    "meta": {"requestUuid": "req-2"},
                }
            )
            await handler._handle_context_listener_unsubscribe(unsub_req, ws)
            cs.listener_store.remove_listener.assert_called_with("listener-1")

    @pytest.mark.asyncio
    async def test_add_intent_listener_and_unsubscribe(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("src-uuid")

        from fdc3.models.dacp.dacp import (
            AddIntentListenerRequest,
            IntentListenerUnsubscribeRequest,
        )

        add_req = AddIntentListenerRequest.model_validate(
            {
                "type": "addIntentListener",
                "payload": {"intent": "ViewChart"},
                "meta": {"requestUuid": "req-1"},
            }
        )

        listener_uuid = ListenerUuid(root="listener-1")

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.add_intent_listener.return_value = SimpleNamespace(
                listener_uuid=listener_uuid
            )

            await handler._handle_add_intent_listener(add_req, session_id, sessions, ws)
            sent = send.call_args.args[1]
            assert sent.payload.listenerUuid.root == "listener-1"

            unsub_req = IntentListenerUnsubscribeRequest.model_validate(
                {
                    "type": "intentListenerUnsubscribe",
                    "payload": {"listenerUuid": "listener-1"},
                    "meta": {"requestUuid": "req-2"},
                }
            )
            await handler._handle_intent_listener_unsubscribe(unsub_req, ws)
            cs.listener_store.remove_listener.assert_called_with("listener-1")


class TestDACPHandlerRaiseIntent:
    @pytest.mark.asyncio
    async def test_raise_intent_system_intent_short_circuit(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "system:test", "context": {"type": "x"}},
                "meta": {
                    "requestUuid": "req-1",
                    "source": {"appId": "a", "instanceId": "i"},
                },
            }
        )

        with (
            patch.object(
                handler.system_intent_handler, "is_system_intent", return_value=True
            ),
            patch.object(
                handler.system_intent_handler,
                "handle_system_intent",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    type="raiseIntentResponse", model_dump_json=lambda: "{}"
                ),
            ),
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            await handler._handle_raise_intent(req, ws)
            send.assert_called_once()

    @pytest.mark.asyncio
    async def test_raise_intent_plugin_handled(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "ViewChart", "context": {"type": "x"}},
                "meta": {"requestUuid": "req-1"},
            }
        )
        with (
            patch.object(
                handler, "_try_plugin_handler", new_callable=AsyncMock
            ) as plugin,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
            patch.object(
                handler.system_intent_handler, "is_system_intent", return_value=False
            ),
        ):
            plugin.return_value = SimpleNamespace(type="raiseIntentResponse")
            await handler._handle_raise_intent(req, ws)
            send.assert_called_once()

    @pytest.mark.asyncio
    async def test_raise_intent_external_handled(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "ViewChart", "context": {"type": "x"}},
                "meta": {"requestUuid": "req-1"},
            }
        )
        with (
            patch.object(
                handler,
                "_try_plugin_handler",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                handler, "_try_external_handler", new_callable=AsyncMock
            ) as ext,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
            patch.object(
                handler.system_intent_handler, "is_system_intent", return_value=False
            ),
        ):
            ext.return_value = SimpleNamespace(type="raiseIntentResponse")
            await handler._handle_raise_intent(req, ws)
            send.assert_called_once()

    @pytest.mark.asyncio
    async def test_raise_intent_normal_resolution_and_intent_event(self):
        handler, _, _, connection_manager = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "ViewChart", "context": {"type": "x"}},
                "meta": {
                    "requestUuid": "req-1",
                    "source": {"appId": "source", "instanceId": "inst"},
                },
            }
        )

        resolution = IntentResolution(
            source=AppIdentifier(
                appId="target", instanceId="target-inst", desktopAgent=None
            ),
            intent="ViewChart",
        )

        with (
            patch.object(
                handler,
                "_try_plugin_handler",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                handler,
                "_try_external_handler",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
            patch.object(
                handler.system_intent_handler, "is_system_intent", return_value=False
            ),
        ):
            cs.intent_resolver.resolve_intent.return_value = resolution
            cs.intent_resolver.deliver_intent_event.return_value = ["t1"]

            await handler._handle_raise_intent(req, ws)

            # Response + event delivery
            assert send.await_count == 1
            assert connection_manager.send_to_instance.await_count == 1

    @pytest.mark.asyncio
    async def test_raise_intent_no_apps_found(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "ViewChart", "context": {"type": "x"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with (
            patch.object(
                handler,
                "_try_plugin_handler",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                handler,
                "_try_external_handler",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
            patch.object(
                handler.system_intent_handler, "is_system_intent", return_value=False
            ),
        ):
            cs.intent_resolver.resolve_intent.return_value = None

            await handler._handle_raise_intent(req, ws)

            sent = send.call_args.args[1]
            assert sent.type == "raiseIntentResponse"
            assert sent.payload.error == "NoAppsFound"

    @pytest.mark.asyncio
    async def test_raise_intent_for_context_no_apps_found(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentForContextRequest

        req = RaiseIntentForContextRequest.model_validate(
            {
                "type": "raiseIntentForContext",
                "payload": {"context": {"type": "t"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.intent_listeners = {}
            await handler._handle_raise_intent_for_context(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "raiseIntentForContextResponse"
            assert sent.payload.error == "NoAppsFound"

    @pytest.mark.asyncio
    async def test_raise_intent_for_context_ambiguous_intents_returns_resolver_unavailable(
        self,
    ):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentForContextRequest

        req = RaiseIntentForContextRequest.model_validate(
            {
                "type": "raiseIntentForContext",
                "payload": {"context": {"type": "t"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.intent_listeners = {
                "l1": SimpleNamespace(intent="ViewChart"),
                "l2": SimpleNamespace(intent="ViewNews"),
            }
            await handler._handle_raise_intent_for_context(req, ws)
            sent = send.call_args.args[1]
            assert sent.type == "raiseIntentForContextResponse"
            assert sent.payload.error == "ResolverUnavailable"

    @pytest.mark.asyncio
    async def test_raise_intent_for_context_single_intent_resolves_and_emits_event(
        self,
    ):
        handler, _, _, connection_manager = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentForContextRequest
        from fdc3.desktop_agent.api import IntentResolution
        from fdc3.models.identifiers import AppIdentifier

        req = RaiseIntentForContextRequest.model_validate(
            {
                "type": "raiseIntentForContext",
                "payload": {"context": {"type": "t"}},
                "meta": {
                    "requestUuid": "req-1",
                    "source": {"appId": "source", "instanceId": "inst"},
                },
            }
        )

        resolution = IntentResolution(
            source=AppIdentifier(appId="target", instanceId="target-inst"),
            intent="ViewChart",
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.listener_store.intent_listeners = {
                "l1": SimpleNamespace(intent="ViewChart")
            }
            cs.intent_resolver.resolve_intent.return_value = resolution
            cs.intent_resolver.deliver_intent_event.return_value = ["t1"]

            await handler._handle_raise_intent_for_context(req, ws)

            sent = send.call_args.args[1]
            assert sent.type == "raiseIntentForContextResponse"
            assert sent.payload.intentResolution.intent == "ViewChart"
            assert connection_manager.send_to_instance.await_count == 1

    @pytest.mark.asyncio
    async def test_intent_result_and_heartbeat_paths(self):
        handler, _, _, _ = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import (
            HeartbeatAcknowledgmentRequest,
            IntentResultRequest,
            RaiseIntentResultResponse,
        )

        intent_req = IntentResultRequest.model_validate(
            {
                "type": "intentResultRequest",
                "payload": {"intentResult": {"type": "t"}},
                "meta": {"requestUuid": "req-1"},
            }
        )
        rir = RaiseIntentResultResponse.model_validate(
            {
                "type": "raiseIntentResultResponse",
                "payload": {},
                "meta": {"requestUuid": "req-2"},
            }
        )
        hb = HeartbeatAcknowledgmentRequest.model_validate(
            {
                "type": "heartbeatAcknowledgmentRequest",
                "payload": {"heartbeatEventUuid": "evt-1"},
                "meta": {"requestUuid": "req-3"},
            }
        )

        with patch.object(handler, "_send_model", new_callable=AsyncMock) as send:
            await handler._handle_intent_result_request(intent_req, ws)
            await handler._handle_raise_intent_result_response(rir)
            await handler._handle_heartbeat_acknowledgment(hb)

            sent = send.call_args.args[1]
            assert sent.type == "intentResultResponse"


class TestDACPHandlerExternalHandlers:
    @pytest.mark.asyncio
    async def test_register_unregister_external_handler_success(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("src-uuid")

        from fdc3.models.dacp.external_models import (
            RegisterExternalHandlerRequest,
            UnregisterExternalHandlerRequest,
        )

        reg = RegisterExternalHandlerRequest.model_validate(
            {
                "type": "registerExternalHandler",
                "payload": {
                    "handler_id": "h1",
                    "intents": ["ViewChart"],
                    "priority": 1,
                    "metadata": {"name": "x"},
                },
                "meta": {"requestUuid": "req-1"},
            }
        )

        unreg = UnregisterExternalHandlerRequest.model_validate(
            {
                "type": "unregisterExternalHandler",
                "payload": {"handler_uuid": "handler-uuid"},
                "meta": {"requestUuid": "req-2"},
            }
        )

        with patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs:
            cs.register_external_handler = AsyncMock(return_value="handler-uuid")
            cs.unregister_external_handler = AsyncMock(return_value=None)

            await handler._handle_register_external_handler(
                reg, session_id, sessions, ws
            )
            await handler._handle_unregister_external_handler(
                unreg, session_id, sessions, ws
            )

        assert ws.send_text.await_count == 2

    @pytest.mark.asyncio
    async def test_register_external_handler_failure_sends_internal_error(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("src-uuid")

        from fdc3.models.dacp.external_models import RegisterExternalHandlerRequest

        reg = RegisterExternalHandlerRequest.model_validate(
            {
                "type": "registerExternalHandler",
                "payload": {
                    "handler_id": "h1",
                    "intents": ["ViewChart"],
                    "priority": 1,
                    "metadata": {"name": "x"},
                },
                "meta": {"requestUuid": "req-1"},
            }
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.register_external_handler = AsyncMock(side_effect=RuntimeError("boom"))
            await handler._handle_register_external_handler(
                reg, session_id, sessions, ws
            )

            sent = send.call_args.args[1]
            assert sent.type == "registerExternalHandlerResponse"
            assert sent.payload.error == "InternalError"

    @pytest.mark.asyncio
    async def test_unregister_external_handler_failure_sends_internal_error(self):
        handler, _, _, _ = _handler()
        ws = _websocket()
        session_id, sessions = _wcp_sessions("src-uuid")

        from fdc3.models.dacp.external_models import UnregisterExternalHandlerRequest

        unreg = UnregisterExternalHandlerRequest.model_validate(
            {
                "type": "unregisterExternalHandler",
                "payload": {"handler_uuid": "handler-uuid"},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(handler, "_send_model", new_callable=AsyncMock) as send,
        ):
            cs.unregister_external_handler = AsyncMock(side_effect=RuntimeError("boom"))
            await handler._handle_unregister_external_handler(
                unreg, session_id, sessions, ws
            )

            sent = send.call_args.args[1]
            assert sent.type == "unregisterExternalHandlerResponse"
            assert sent.payload.error == "InternalError"

    @pytest.mark.asyncio
    async def test_external_intent_result_resolves_pending(self):
        handler, _, _, _ = _handler()

        from fdc3.models.dacp.external_models import ExternalIntentResultRequest

        req = ExternalIntentResultRequest.model_validate(
            {
                "type": "intentResult",
                "payload": {
                    "request_uuid": "req-1",
                    "result": {"ok": True},
                    "error": None,
                },
            }
        )

        with patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs:
            await handler._handle_external_intent_result(req)
            cs.resolve_pending_intent.assert_called_once()

    @pytest.mark.asyncio
    async def test_external_intent_result_failure_is_logged(self):
        handler, _, _, _ = _handler()

        from fdc3.models.dacp.external_models import ExternalIntentResultRequest

        req = ExternalIntentResultRequest.model_validate(
            {
                "type": "intentResult",
                "payload": {"request_uuid": "req-1", "result": None, "error": "x"},
            }
        )

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch("fdc3.desktop_agent.handlers.dacp.logger") as mock_logger,
        ):
            cs.resolve_pending_intent.side_effect = RuntimeError("boom")
            await handler._handle_external_intent_result(req)
            mock_logger.exception.assert_called()

    @pytest.mark.asyncio
    async def test_try_plugin_handler_paths(self):
        handler, _, _, _ = _handler()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "ViewChart", "context": {"type": "t"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        plugin = SimpleNamespace(name="p1", handle_intent=AsyncMock())

        with patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs:
            # handled + error
            cs.plugin_registry.get_plugins_for_intent.return_value = [plugin]
            plugin.handle_intent.return_value = SimpleNamespace(
                handled=True, error="Nope"
            )
            resp = await handler._try_plugin_handler(req)
            assert resp is not None
            assert resp.type == "raiseIntentResponse"
            assert isinstance(resp.payload, ErrorResponsePayload)
            assert resp.payload.error == "Nope"

            # handled + ok
            plugin.handle_intent.return_value = SimpleNamespace(
                handled=True, error=None
            )
            resp2 = await handler._try_plugin_handler(req)
            assert resp2 is not None
            assert resp2.type == "raiseIntentResponse"

            # plugin exception -> logged, continue -> None
            plugin.handle_intent.side_effect = RuntimeError("boom")
            cs.plugin_registry.get_plugins_for_intent.return_value = [plugin]
            with patch("fdc3.desktop_agent.handlers.dacp.logger") as mock_logger:
                resp3 = await handler._try_plugin_handler(req)
                assert resp3 is None
                mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_try_external_handler_success_and_error_paths(self):
        handler, _, _, connection_manager = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "ViewChart", "context": {"type": "x"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        with patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs:
            cs.external_registry.get_handlers_for_intent.return_value = []
            assert await handler._try_external_handler(req, ws) is None

            # Forwarding failure
            cs.external_registry.get_handlers_for_intent.return_value = [
                SimpleNamespace(handler_id="h1", instance_uuid="inst-uuid")
            ]
            cs.create_pending_intent.side_effect = (
                lambda _: asyncio.get_running_loop().create_future()
            )
            connection_manager.send_to_instance.side_effect = RuntimeError(
                "send failed"
            )

            assert await handler._try_external_handler(req, ws) is None
            cs.resolve_pending_intent.assert_called()

        # Timeout without waiting 30s
        handler, _, _, _ = _handler()
        ws = _websocket()

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch(
                "fdc3.desktop_agent.handlers.dacp.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ),
        ):
            cs.external_registry.get_handlers_for_intent.return_value = [
                SimpleNamespace(handler_id="h1", instance_uuid="inst-uuid")
            ]
            cs.create_pending_intent.side_effect = (
                lambda _: asyncio.get_running_loop().create_future()
            )
            assert await handler._try_external_handler(req, ws) is None

        # Success path
        handler, _, _, _ = _handler()
        ws = _websocket()

        with patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs:
            cs.external_registry.get_handlers_for_intent.return_value = [
                SimpleNamespace(handler_id="h1", instance_uuid="inst-uuid")
            ]

            fut = asyncio.get_running_loop().create_future()
            cs.create_pending_intent.return_value = fut
            asyncio.get_running_loop().call_soon(fut.set_result, {"ok": True})

            resp = await handler._try_external_handler(req, ws)
            assert resp is not None
            assert resp.type == "raiseIntentResponse"

    @pytest.mark.asyncio
    async def test_try_external_handler_failed_and_none_result(self):
        handler, _, _, connection_manager = _handler()
        ws = _websocket()

        from fdc3.models.dacp.dacp import RaiseIntentRequest

        req = RaiseIntentRequest.model_validate(
            {
                "type": "raiseIntent",
                "payload": {"intent": "ViewChart", "context": {"type": "x"}},
                "meta": {"requestUuid": "req-1"},
            }
        )

        ext_handler = SimpleNamespace(handler_id="h1", instance_uuid="inst-uuid")
        fut = asyncio.get_running_loop().create_future()
        fut.set_result({"ok": True})

        with (
            patch("fdc3.desktop_agent.handlers.dacp.core_services") as cs,
            patch.object(
                connection_manager, "send_to_instance", new_callable=AsyncMock
            ) as send_to,
            patch(
                "fdc3.desktop_agent.handlers.dacp.asyncio.wait_for",
                new_callable=AsyncMock,
            ) as wf,
        ):
            cs.external_registry.get_handlers_for_intent.return_value = [ext_handler]
            cs.create_pending_intent.return_value = fut
            send_to.return_value = None

            # Non-timeout exception while waiting
            wf.side_effect = RuntimeError("boom")
            assert await handler._try_external_handler(req, ws) is None

            # None result
            wf.side_effect = None
            wf.return_value = None
            assert await handler._try_external_handler(req, ws) is None

            assert send_to.await_count == 2
