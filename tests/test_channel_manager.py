import asyncio
from datetime import datetime
from typing import Any, cast
from unittest.mock import patch

import pytest

from fdc3.desktop_agent.api import DisplayMetadata
from fdc3.desktop_agent.distributed.adapter import DistributedLogAdapter
from fdc3.desktop_agent.core.channel_manager import ChannelManager
from fdc3.desktop_agent.core.channel_types import ChannelEvent
from fdc3.models.context_types import Instrument


class TestChannelManagerCoverage:
    def test_create_channel_emits_created_event(self):
        manager = ChannelManager()
        events: list[ChannelEvent] = []

        sub_id = manager.subscribe_to_events(events.append)
        try:
            manager.create_channel("c1", "user")
        finally:
            manager.unsubscribe_from_events(sub_id)

        assert any(
            e["event_type"] == "created" and e["channel_id"] == "c1" for e in events
        )

    def test_join_channel_switches_and_emits_left_joined(self):
        manager = ChannelManager()
        events: list[ChannelEvent] = []
        manager.subscribe_to_events(events.append)

        manager.create_channel("c1", "user")
        manager.create_channel("c2", "user")

        manager.join_channel("inst", "c1")
        manager.join_channel("inst", "c2")

        current = manager.get_current_channel("inst")
        assert current is not None
        assert current.id == "c2"
        assert "inst" not in manager.get_channel_members("c1")
        assert "inst" in manager.get_channel_members("c2")

        # When switching, should emit both left and joined events.
        assert any(
            e["event_type"] == "left" and e["channel_id"] == "c1" for e in events
        )
        assert any(
            e["event_type"] == "joined" and e["channel_id"] == "c2" for e in events
        )

    def test_join_channel_unknown_channel_noop(self):
        manager = ChannelManager()
        manager.join_channel("inst", "missing")
        assert manager.get_current_channel("inst") is None

    def test_leave_current_channel_missing_channel_in_mapping(self):
        manager = ChannelManager()
        manager.instance_channels["inst"] = "missing"
        manager.leave_current_channel("inst")
        assert "inst" not in manager.instance_channels

    def test_get_channel_members_unknown_returns_empty(self):
        manager = ChannelManager()
        assert manager.get_channel_members("missing") == []

    def test_list_channels_returns_instances(self):
        manager = ChannelManager()
        manager.create_channel("c1", "user")
        manager.create_channel("c2", "user")

        channels = manager.list_channels()
        assert {c.id for c in channels} == {"c1", "c2"}

    def test_get_channel_info_with_and_without_metadata(self):
        manager = ChannelManager()
        meta = DisplayMetadata(name="Red", color="0xFF0000")
        manager.create_channel("c1", "user", display_metadata=meta)
        manager.create_channel("c2", "user")

        info1 = manager.get_channel_info("c1")
        assert info1 is not None
        assert info1["display_name"] == "Red"
        assert info1["color"] == "0xFF0000"

        info2 = manager.get_channel_info("c2")
        assert info2 is not None
        assert info2["display_name"] is None
        assert info2["color"] is None

        assert manager.get_channel_info("missing") is None

    def test_subscribe_channel_filter(self):
        manager = ChannelManager()
        c1_events: list[ChannelEvent] = []
        manager.subscribe_to_events(c1_events.append, channel_filter="c1")

        manager.create_channel("c1", "user")
        manager.create_channel("c2", "user")

        assert any(e["channel_id"] == "c1" for e in c1_events)
        assert all(e["channel_id"] == "c1" for e in c1_events)

    @pytest.mark.asyncio
    async def test_emit_event_async_callback_is_scheduled(self):
        manager = ChannelManager()
        ran = asyncio.Event()

        async def _handler(event: ChannelEvent) -> None:
            assert event["event_type"] == "created"
            ran.set()

        def callback(event: ChannelEvent):
            return _handler(event)

        manager.subscribe_to_events(callback)
        manager.create_channel("c1", "user")

        await asyncio.wait_for(ran.wait(), timeout=1.0)

    def test_emit_event_callback_exception_is_logged(self):
        manager = ChannelManager()

        def bad_callback(_: ChannelEvent) -> None:
            raise RuntimeError("boom")

        manager.subscribe_to_events(bad_callback)

        with patch("fdc3.desktop_agent.core.channel_events.logger") as mock_logger:
            manager.create_channel("c1", "user")
            mock_logger.exception.assert_called()

    @pytest.mark.asyncio
    async def test_emit_event_async_callback_no_running_loop_logs(self):
        manager = ChannelManager()

        async def _coro(_: ChannelEvent) -> None:
            return None

        def callback(event: ChannelEvent):
            return _coro(event)

        manager.subscribe_to_events(callback)

        with (
            patch(
                "fdc3.desktop_agent.core.channel_events.asyncio.get_running_loop",
                side_effect=RuntimeError,
            ),
            patch(
                "fdc3.desktop_agent.core.channel_events.asyncio.get_event_loop",
                side_effect=RuntimeError,
            ),
            patch("fdc3.desktop_agent.core.channel_events.logger") as mock_logger,
        ):
            manager.create_channel("c1", "user")
            mock_logger.exception.assert_any_call(
                "Failed to schedule async channel callback"
            )

    @pytest.mark.asyncio
    async def test_distributed_publish_scheduled_and_remote_suppresses(self):
        manager = ChannelManager()

        published = asyncio.Event()
        published_payload: dict | None = None

        class DummyAdapter(DistributedLogAdapter):
            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                return None

            async def publish(self, topic: str, message: Any) -> None:
                nonlocal published_payload
                assert topic == "channel_events"
                published_payload = cast(ChannelEvent, message)
                published.set()

            async def subscribe(self, topic: str, callback):
                return "sub"

            async def unsubscribe(self, subscription_id: str) -> None:
                return None

        manager.distributed_adapter = cast(DistributedLogAdapter, DummyAdapter())

        tasks: list[asyncio.Task] = []

        def fake_create_task_safe(coro, *, name=None):
            t = asyncio.create_task(coro)
            tasks.append(t)
            return t

        with patch(
            "fdc3.desktop_agent.tools.create_task_safe",
            side_effect=fake_create_task_safe,
        ):
            manager.create_channel("c1", "user")
            await asyncio.wait_for(published.wait(), timeout=1.0)

            assert published_payload is not None
            assert published_payload["event_type"] == "created"

            # If remote=True, should not re-publish to distributed adapter.
            published.clear()
            manager._emit_event("created", "c1", remote=True)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(published.wait(), timeout=0.05)

        # Ensure any scheduled tasks are cleaned up.
        for t in tasks:
            await t

    def test_distributed_publish_schedule_failure_is_logged(self):
        manager = ChannelManager()

        class DummyAdapter(DistributedLogAdapter):
            async def start(self) -> None:
                return None

            async def stop(self) -> None:
                return None

            async def publish(self, topic: str, message: Any) -> None:
                return None

            async def subscribe(self, topic: str, callback):
                return "sub"

            async def unsubscribe(self, subscription_id: str) -> None:
                return None

        manager.distributed_adapter = cast(DistributedLogAdapter, DummyAdapter())

        with (
            patch(
                "fdc3.desktop_agent.core.channel_events.create_task_safe",
                side_effect=RuntimeError("nope"),
            ),
            patch("fdc3.desktop_agent.core.channel_events.logger") as mock_logger,
        ):
            manager.create_channel("c1", "user")
            mock_logger.exception.assert_any_call(
                "Failed to schedule distributed publish task"
            )

    @pytest.mark.asyncio
    async def test_publish_event_adapter_none_and_exception_swallowed(self):
        manager = ChannelManager()

        # adapter None -> returns without error
        manager.distributed_adapter = None
        await manager._publish_event(_make_event())

        class FailingAdapter:
            async def publish(self, topic: str, message: Any) -> None:
                raise RuntimeError("fail")

        manager.distributed_adapter = cast(DistributedLogAdapter, FailingAdapter())
        await manager._publish_event(_make_event())

    def test_broadcast_to_channel_emits_context_json(self):
        manager = ChannelManager()
        events: list[ChannelEvent] = []
        manager.subscribe_to_events(events.append)

        manager.create_channel("c1", "user")
        manager.join_channel("inst", "c1")

        ctx: Instrument = {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}}
        manager.broadcast_to_channel("c1", ctx, source_instance_uuid="inst")

        broadcast_events = [e for e in events if e["event_type"] == "broadcast"]
        assert broadcast_events
        assert broadcast_events[-1]["instance_uuid"] == "inst"
        assert broadcast_events[-1]["context"] == json_dumps(ctx)

        # Unknown channel should not emit.
        count_before = len(events)
        manager.broadcast_to_channel("missing", ctx, source_instance_uuid="inst")
        assert len(events) == count_before


def json_dumps(value: object) -> str:
    # Match ChannelManager behavior for context serialization.
    import json

    return json.dumps(value)


def _make_event() -> ChannelEvent:
    return {
        "event_type": "created",
        "channel_id": "c1",
        "instance_uuid": None,
        "context": None,
        "timestamp": datetime.now().isoformat(),
    }
