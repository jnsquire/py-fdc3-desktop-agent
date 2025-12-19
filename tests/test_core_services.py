# Core service tests

import pytest
from fdc3.desktop_agent.core.app_registry import AppRegistry
from fdc3.desktop_agent.core.listener_store import ListenerStore
from fdc3.desktop_agent.core.context_router import ContextRouter
from fdc3.desktop_agent.core.intent_resolver import IntentResolver
from fdc3.desktop_agent.core.channel_manager import ChannelManager
from fdc3.models.primitives import ListenerUuid
from fdc3.models.identifiers import AppIdentifier


class TestAppRegistry:
    """Test AppRegistry functionality"""

    def test_register_instance(self):
        """Test registering app instances"""
        registry = AppRegistry()

        instance = registry.register_instance("test-app", "instance1", "uuid1")
        assert instance.app_id == "test-app"
        assert instance.instance_id == "instance1"
        assert instance.instance_uuid == "uuid1"
        assert instance.connected is True

        # Check retrieval
        retrieved = registry.get_instance("uuid1")
        assert retrieved == instance

    def test_register_pending_instance(self):
        """Test registering pending instances"""
        registry = AppRegistry()

        instance = registry.register_pending_instance("test-app", "instance1", "uuid1")
        assert instance.app_id == "test-app"
        assert instance.connected is False

        # Mark as connected
        registry.register_instance("test-app", "instance1", "uuid1")
        retrieved = registry.get_instance("uuid1")
        assert retrieved is not None
        assert retrieved.connected is True

    def test_get_instances_for_app(self):
        """Test getting instances for an app"""
        registry = AppRegistry()

        registry.register_instance("test-app", "instance1", "uuid1")
        registry.register_instance("test-app", "instance2", "uuid2")
        registry.register_instance("other-app", "instance1", "uuid3")

        instances = registry.get_instances_for_app("test-app")
        assert len(instances) == 2
        assert all(inst.app_id == "test-app" for inst in instances)

        connected_instances = registry.get_connected_instances_for_app("test-app")
        assert len(connected_instances) == 2

    def test_unregister_instance(self):
        """Test unregistering instances"""
        registry = AppRegistry()

        registry.register_instance("test-app", "instance1", "uuid1")
        assert registry.get_instance("uuid1") is not None

        registry.unregister_instance("uuid1")
        assert registry.get_instance("uuid1") is None

    @pytest.mark.asyncio
    async def test_wait_for_instance_connection(self):
        """Test waiting for instance connection events"""
        registry = AppRegistry()

        # Register pending instance
        pending = registry.register_pending_instance("test-app", "instance1", "uuid1")
        assert pending.connected is False

        # Start waiting for connection (should timeout since we don't connect it)
        connected = await registry.wait_for_instance_connection("uuid1", timeout=0.01)
        assert connected is False

        # Now register as connected
        registry.register_instance("test-app", "instance1", "uuid1")
        retrieved = registry.get_instance("uuid1")
        assert retrieved is not None
        assert retrieved.connected is True

        # Waiting for already connected instance should return immediately
        connected = await registry.wait_for_instance_connection("uuid1", timeout=1.0)
        assert connected is True


class TestListenerStore:
    """Test ListenerStore functionality"""

    def test_add_context_listener(self):
        """Test adding context listeners"""
        store = ListenerStore()

        listener = store.add_context_listener(
            ListenerUuid(), "instance1", "fdc3.instrument"
        )
        assert listener.instance_uuid == "instance1"
        assert listener.context_type == "fdc3.instrument"
        assert isinstance(listener.listener_uuid, ListenerUuid)

    def test_add_intent_listener(self):
        """Test adding intent listeners"""
        store = ListenerStore()

        listener = store.add_intent_listener(
            ListenerUuid("uuid1"), "instance1", "ViewChart"
        )
        assert listener.instance_uuid == "instance1"
        assert listener.intent == "ViewChart"
        assert isinstance(listener.listener_uuid, ListenerUuid)

    def test_get_context_listeners(self):
        """Test getting context listeners"""
        store = ListenerStore()

        store.add_context_listener(
            ListenerUuid("uuid1"), "instance1", "fdc3.instrument"
        )
        store.add_context_listener(
            ListenerUuid("uuid2"), "instance2", "fdc3.instrument"
        )
        store.add_context_listener(ListenerUuid("uuid3"), "instance1", "fdc3.contact")

        listeners = store.get_context_listeners("fdc3.instrument")
        assert len(listeners) == 2
        assert all(listener.context_type == "fdc3.instrument" for listener in listeners)

    def test_get_intent_listeners(self):
        """Test getting intent listeners"""
        store = ListenerStore()

        store.add_intent_listener(ListenerUuid("uuid1"), "instance1", "ViewChart")
        store.add_intent_listener(ListenerUuid("uuid2"), "instance2", "ViewChart")
        store.add_intent_listener(
            ListenerUuid("uuid3"), "instance1", "CreateInteraction"
        )

        listeners = store.get_intent_listeners_for_intent("ViewChart")
        assert len(listeners) == 2
        assert all(listener.intent == "ViewChart" for listener in listeners)

    def test_remove_listener(self):
        """Test removing listeners"""
        store = ListenerStore()

        listener = store.add_context_listener(
            ListenerUuid("uuid1"), "instance1", "fdc3.instrument"
        )
        assert len(store.get_context_listeners("fdc3.instrument")) == 1

        store.remove_listener(listener.listener_uuid.root)
        assert len(store.get_context_listeners("fdc3.instrument")) == 0

    def test_remove_listeners_for_instance(self):
        """Test removing all listeners for an instance"""
        store = ListenerStore()

        store.add_context_listener(
            ListenerUuid("uuid1"), "instance1", "fdc3.instrument"
        )
        store.add_intent_listener(ListenerUuid("uuid2"), "instance1", "ViewChart")
        store.add_context_listener(
            ListenerUuid("uuid3"), "instance2", "fdc3.instrument"
        )

        assert len(store.get_context_listeners("fdc3.instrument")) == 2
        assert len(store.get_intent_listeners_for_intent("ViewChart")) == 1

        store.remove_listeners_for_instance("instance1")

        assert len(store.get_context_listeners("fdc3.instrument")) == 1
        assert len(store.get_intent_listeners_for_intent("ViewChart")) == 0


class TestContextRouter:
    """Test ContextRouter functionality"""

    def test_broadcast_routing_no_echo(self):
        """Test that broadcasts don't echo back to sender"""
        registry = AppRegistry()
        store = ListenerStore()
        channel_manager = ChannelManager()
        router = ContextRouter(store, channel_manager, registry)

        # Register instances
        registry.register_instance("app1", "inst1", "uuid1")
        registry.register_instance("app2", "inst1", "uuid2")

        # Add listeners
        store.add_context_listener(
            ListenerUuid("listener1"), "uuid1", "fdc3.instrument"
        )
        store.add_context_listener(
            ListenerUuid("listener2"), "uuid2", "fdc3.instrument"
        )

        # Broadcast from uuid1
        targets = router.broadcast_context({"type": "fdc3.instrument"}, "uuid1")

        # Should only target uuid2, not uuid1 (no echo)
        assert "uuid2" in targets
        assert "uuid1" not in targets

    def test_broadcast_validation(self):
        """Test that broadcasts require context.type"""
        registry = AppRegistry()
        store = ListenerStore()
        channel_manager = ChannelManager()
        router = ContextRouter(store, channel_manager, registry)

        # Try to broadcast without type
        with pytest.raises(ValueError):
            router.broadcast_context({}, "uuid1")

        # Try to broadcast with type
        targets = router.broadcast_context({"type": "fdc3.instrument"}, "uuid1")
        assert isinstance(targets, list)  # Should not raise

    def test_broadcast_context_validation_requires_type(self):
        """Test that broadcast validation requires context.type"""
        registry = AppRegistry()
        store = ListenerStore()
        manager = ChannelManager()
        router = ContextRouter(store, manager, registry)

        # Context without type should raise ValueError
        with pytest.raises(ValueError, match="Context must have a 'type' field"):
            router.broadcast_context({"id": "test"}, "source-uuid")

    def test_broadcast_context_no_echo_policy(self):
        """Test that broadcast avoids echoing to source instance"""
        registry = AppRegistry()
        store = ListenerStore()
        manager = ChannelManager()
        router = ContextRouter(store, manager, registry)

        # Register instances
        registry.register_instance("app1", "inst1", "source-uuid")
        registry.register_instance("app2", "inst1", "target-uuid")

        # Add context listener for source (should be excluded)
        store.add_context_listener(
            ListenerUuid("listener1"), "source-uuid", "fdc3.instrument"
        )
        # Add context listener for target (should receive)
        store.add_context_listener(
            ListenerUuid("listener2"), "target-uuid", "fdc3.instrument"
        )

        # Broadcast from source
        targets = router.broadcast_context(
            {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}}, "source-uuid"
        )

        # Should only target the other instance, not the source
        assert "target-uuid" in targets
        assert "source-uuid" not in targets

    def test_broadcast_context_to_listeners(self):
        """Test that broadcast reaches context listeners"""
        registry = AppRegistry()
        store = ListenerStore()
        manager = ChannelManager()
        router = ContextRouter(store, manager, registry)

        # Register instances
        registry.register_instance("app1", "inst1", "uuid1")
        registry.register_instance("app2", "inst1", "uuid2")

        # Add context listeners
        store.add_context_listener(
            ListenerUuid("listener1"), "uuid1", "fdc3.instrument"
        )
        store.add_context_listener(
            ListenerUuid("listener2"), "uuid2", "fdc3.instrument"
        )

        # Broadcast
        targets = router.broadcast_context(
            {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}}, "uuid3"
        )

        # Both listeners should receive (no echo since source is different)
        assert len(targets) == 2
        assert "uuid1" in targets
        assert "uuid2" in targets


class TestIntentResolver:
    """Test IntentResolver functionality"""

    def test_resolve_intent_with_listeners(self):
        """Test resolving intents when listeners exist"""
        registry = AppRegistry()
        store = ListenerStore()
        resolver = IntentResolver(store, registry)

        # Register instance and listener
        registry.register_instance("app1", "inst1", "uuid1")
        store.add_intent_listener(ListenerUuid("listener1"), "uuid1", "ViewChart")

        # Resolve intent
        resolution = resolver.resolve_intent("ViewChart", {"type": "fdc3.instrument"})

        assert resolution is not None
        assert resolution.intent == "ViewChart"
        assert resolution.source.appId == "app1"

    def test_resolve_intent_no_listeners(self):
        """Test resolving intents when no listeners exist"""
        registry = AppRegistry()
        store = ListenerStore()
        resolver = IntentResolver(store, registry)

        # Resolve intent without listeners
        resolution = resolver.resolve_intent("ViewChart", {"type": "fdc3.instrument"})

        assert resolution is None

    def test_deliver_intent_event(self):
        """Test delivering intent events to listeners"""
        registry = AppRegistry()
        store = ListenerStore()
        resolver = IntentResolver(store, registry)

        # Register instances and listeners
        registry.register_instance("app1", "inst1", "uuid1")
        registry.register_instance("app2", "inst1", "uuid2")
        store.add_intent_listener(ListenerUuid("listener1"), "uuid1", "ViewChart")
        store.add_intent_listener(ListenerUuid("listener2"), "uuid2", "ViewChart")

        # Deliver event
        targets = resolver.deliver_intent_event(
            "ViewChart", {"type": "fdc3.instrument"}, None
        )

        assert len(targets) == 2
        assert "uuid1" in targets
        assert "uuid2" in targets

    def test_raise_intent_flow(self):
        """Test the complete raiseIntent → intentEvent → intentResultRequest → raiseIntentResultResponse flow"""
        registry = AppRegistry()
        store = ListenerStore()
        resolver = IntentResolver(store, registry)

        # Register instances
        registry.register_instance("source-app", "inst1", "source-uuid")
        registry.register_instance("target-app", "inst1", "target-uuid")

        # Add intent listener
        store.add_intent_listener(ListenerUuid("listener1"), "target-uuid", "ViewChart")

        # Resolve intent
        resolution = resolver.resolve_intent(
            "ViewChart", {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}}, None
        )

        assert resolution is not None
        assert resolution.intent == "ViewChart"
        assert resolution.source.appId == "target-app"

        # Test intent event delivery
        originating_app = AppIdentifier(
            appId="source-app", instanceId="source-instance", desktopAgent=None
        )
        targets = resolver.deliver_intent_event(
            "ViewChart",
            {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}},
            originating_app,
        )

        assert "target-uuid" in targets


class TestChannelManager:
    """Test ChannelManager functionality"""

    def test_join_channel(self):
        """Test joining channels"""
        registry = AppRegistry()
        manager = ChannelManager()

        # Register instance
        registry.register_instance("app1", "inst1", "uuid1")

        # Create channel first
        manager.create_channel("user-channel-1", "user")

        # Join channel
        manager.join_channel("uuid1", "user-channel-1")

        # Check current channel
        current_channel = manager.get_current_channel("uuid1")
        assert current_channel is not None
        assert current_channel.id == "user-channel-1"

    def test_leave_channel(self):
        """Test leaving channels"""
        registry = AppRegistry()
        manager = ChannelManager()

        # Register instance and join channel
        registry.register_instance("app1", "inst1", "uuid1")
        manager.create_channel("user-channel-1", "user")
        manager.join_channel("uuid1", "user-channel-1")

        # Leave channel
        manager.leave_current_channel("uuid1")

        # Check no current channel
        assert manager.get_current_channel("uuid1") is None

    def test_get_channel_members(self):
        """Test getting channel members"""
        registry = AppRegistry()
        manager = ChannelManager()

        # Register instances and join channel
        registry.register_instance("app1", "inst1", "uuid1")
        registry.register_instance("app2", "inst1", "uuid2")
        manager.create_channel("user-channel-1", "user")
        manager.join_channel("uuid1", "user-channel-1")
        manager.join_channel("uuid2", "user-channel-1")

        # Get members
        members = manager.get_channel_members("user-channel-1")
        assert len(members) == 2
        assert "uuid1" in members
        assert "uuid2" in members
