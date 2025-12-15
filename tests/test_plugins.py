"""Tests for the plugin system."""

import pytest
from typing import Dict, Any, List, Optional

from fdc3.desktop_agent.plugins import (
    IntentHandlerPlugin,
    IntentHandlerResult,
    PluginRegistry,
)
from fdc3.desktop_agent.core import CoreServices


class SimpleTestPlugin(IntentHandlerPlugin):
    """A simple test plugin for testing."""

    def __init__(self, intents: List[str], priority: int = 0):
        self._intents = intents
        self._priority = priority
        self.calls: List[tuple] = []
        self.registered = False

    @property
    def handled_intents(self) -> List[str]:
        return self._intents

    @property
    def priority(self) -> int:
        return self._priority

    async def on_register(self, core_services: Any) -> None:
        self.registered = True

    async def on_unregister(self) -> None:
        self.registered = False

    async def handle_intent(
        self,
        intent: str,
        context: Optional[Dict[str, Any]],
        source: Optional[Dict[str, Any]],
    ) -> IntentHandlerResult:
        self.calls.append((intent, context, source))
        return IntentHandlerResult(handled=True, result={"plugin": self.name})


class ErrorPlugin(IntentHandlerPlugin):
    """Plugin that raises an exception."""

    @property
    def handled_intents(self) -> List[str]:
        return ["error.intent"]

    async def handle_intent(
        self,
        intent: str,
        context: Optional[Dict[str, Any]],
        source: Optional[Dict[str, Any]],
    ) -> IntentHandlerResult:
        raise RuntimeError("Intentional error")


class FallThroughPlugin(IntentHandlerPlugin):
    """Plugin that returns handled=False to fall through."""

    @property
    def handled_intents(self) -> List[str]:
        return ["fallthrough.intent"]

    async def handle_intent(
        self,
        intent: str,
        context: Optional[Dict[str, Any]],
        source: Optional[Dict[str, Any]],
    ) -> IntentHandlerResult:
        return IntentHandlerResult(handled=False)


class TestPluginRegistry:
    """Tests for PluginRegistry."""

    def test_register_plugin(self):
        """Test basic plugin registration."""
        registry = PluginRegistry()
        plugin = SimpleTestPlugin(["test.intent"])

        registry.register(plugin)

        assert plugin in registry.list_plugins()
        assert "test.intent" in registry.list_handled_intents()
        assert registry.has_handler_for_intent("test.intent")

    def test_unregister_plugin(self):
        """Test plugin unregistration."""
        registry = PluginRegistry()
        plugin = SimpleTestPlugin(["test.intent"])

        registry.register(plugin)
        registry.unregister(plugin)

        assert plugin not in registry.list_plugins()
        assert not registry.has_handler_for_intent("test.intent")

    def test_get_plugins_for_intent(self):
        """Test getting plugins for a specific intent."""
        registry = PluginRegistry()
        plugin1 = SimpleTestPlugin(["shared.intent", "unique1.intent"])
        plugin2 = SimpleTestPlugin(["shared.intent", "unique2.intent"])

        registry.register(plugin1)
        registry.register(plugin2)

        shared_plugins = registry.get_plugins_for_intent("shared.intent")
        assert len(shared_plugins) == 2
        assert plugin1 in shared_plugins
        assert plugin2 in shared_plugins

        unique_plugins = registry.get_plugins_for_intent("unique1.intent")
        assert len(unique_plugins) == 1
        assert plugin1 in unique_plugins

    def test_plugin_priority_ordering(self):
        """Test that plugins are ordered by priority (highest first)."""
        registry = PluginRegistry()
        low_priority = SimpleTestPlugin(["test.intent"], priority=1)
        high_priority = SimpleTestPlugin(["test.intent"], priority=10)
        medium_priority = SimpleTestPlugin(["test.intent"], priority=5)

        registry.register(low_priority)
        registry.register(high_priority)
        registry.register(medium_priority)

        plugins = registry.get_plugins_for_intent("test.intent")
        assert plugins[0] is high_priority
        assert plugins[1] is medium_priority
        assert plugins[2] is low_priority

    def test_duplicate_registration_warning(self):
        """Test that duplicate registration is handled gracefully."""
        registry = PluginRegistry()
        plugin = SimpleTestPlugin(["test.intent"])

        registry.register(plugin)
        registry.register(plugin)  # Should not raise, just warn

        assert registry.list_plugins().count(plugin) == 1

    def test_unregister_not_registered(self):
        """Test unregistering a plugin that was never registered."""
        registry = PluginRegistry()
        plugin = SimpleTestPlugin(["test.intent"])

        registry.unregister(plugin)  # Should not raise


class TestCoreServicesPluginIntegration:
    """Tests for CoreServices plugin integration."""

    @pytest.mark.asyncio
    async def test_register_plugin_calls_on_register(self):
        """Test that registering a plugin calls on_register."""
        services = CoreServices()
        plugin = SimpleTestPlugin(["test.intent"])

        await services.register_plugin(plugin)

        assert plugin.registered is True
        assert plugin in services.plugin_registry.list_plugins()

    @pytest.mark.asyncio
    async def test_unregister_plugin_calls_on_unregister(self):
        """Test that unregistering a plugin calls on_unregister."""
        services = CoreServices()
        plugin = SimpleTestPlugin(["test.intent"])

        await services.register_plugin(plugin)
        await services.unregister_plugin(plugin)

        assert plugin.registered is False
        assert plugin not in services.plugin_registry.list_plugins()


class TestIntentHandlerResult:
    """Tests for IntentHandlerResult."""

    def test_default_values(self):
        """Test default values for IntentHandlerResult."""
        result = IntentHandlerResult()
        assert result.handled is False
        assert result.result is None
        assert result.error is None

    def test_success_result(self):
        """Test successful result."""
        result = IntentHandlerResult(handled=True, result={"data": "value"})
        assert result.handled is True
        assert result.result == {"data": "value"}
        assert result.error is None

    def test_error_result(self):
        """Test error result."""
        result = IntentHandlerResult(handled=True, error="SomethingFailed")
        assert result.handled is True
        assert result.error == "SomethingFailed"


@pytest.mark.asyncio
async def test_plugin_handle_intent():
    """Test that plugin handle_intent is called correctly."""
    plugin = SimpleTestPlugin(["test.intent"])
    context = {"type": "fdc3.instrument", "id": {"ticker": "AAPL"}}
    source = {"appId": "test-app"}

    result = await plugin.handle_intent("test.intent", context, source)

    assert result.handled is True
    assert len(plugin.calls) == 1
    assert plugin.calls[0] == ("test.intent", context, source)


@pytest.mark.asyncio
async def test_fallthrough_plugin():
    """Test plugin that returns handled=False."""
    plugin = FallThroughPlugin()

    result = await plugin.handle_intent("fallthrough.intent", None, None)

    assert result.handled is False


@pytest.mark.asyncio
async def test_error_plugin():
    """Test plugin that raises an exception."""
    plugin = ErrorPlugin()

    with pytest.raises(RuntimeError, match="Intentional error"):
        await plugin.handle_intent("error.intent", None, None)


class TestPluginDiscovery:
    """Tests for plugin entry point discovery."""

    def test_discover_plugins_returns_list(self):
        """Test that discover_plugins returns a list (possibly empty)."""
        from fdc3.desktop_agent.plugins import discover_plugins

        plugins = discover_plugins()
        assert isinstance(plugins, list)
        # All items should be IntentHandlerPlugin instances
        for plugin in plugins:
            assert isinstance(plugin, IntentHandlerPlugin)

    def test_list_plugin_entry_points_returns_list(self):
        """Test that list_plugin_entry_points returns a list of dicts."""
        from fdc3.desktop_agent.plugins import list_plugin_entry_points

        entry_points = list_plugin_entry_points()
        assert isinstance(entry_points, list)
        for ep in entry_points:
            assert isinstance(ep, dict)
            assert "name" in ep
            assert "value" in ep
            assert "group" in ep

    def test_plugin_entry_point_group_constant(self):
        """Test the entry point group constant is correct."""
        from fdc3.desktop_agent.plugins import PLUGIN_ENTRY_POINT_GROUP

        assert PLUGIN_ENTRY_POINT_GROUP == "fdc3.desktop_agent.plugins"

    def test_exports_from_main_package(self):
        """Test discovery functions are exported from main package."""
        from fdc3.desktop_agent import (
            discover_plugins,
            list_plugin_entry_points,
            PLUGIN_ENTRY_POINT_GROUP,
        )

        assert callable(discover_plugins)
        assert callable(list_plugin_entry_points)
        assert isinstance(PLUGIN_ENTRY_POINT_GROUP, str)
