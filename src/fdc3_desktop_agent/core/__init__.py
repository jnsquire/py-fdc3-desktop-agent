# Orchestration and core services

from .app_registry import AppRegistry
from .listener_store import ListenerStore
from .channel_manager import ChannelManager
from .context_router import ContextRouter
from .intent_resolver import IntentResolver

class CoreServices:
    """Central manager for all core services."""

    def __init__(self):
        self.app_registry = AppRegistry()
        self.listener_store = ListenerStore()
        self.channel_manager = ChannelManager()
        self.context_router = ContextRouter(self.listener_store, self.channel_manager, self.app_registry)
        self.intent_resolver = IntentResolver(self.listener_store, self.app_registry)

# Global instance
core_services = CoreServices()