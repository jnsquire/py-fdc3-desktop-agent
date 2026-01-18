from enum import Enum


class PrivateChannelEventListenerTypes(Enum):
    onAddContextListener = "onAddContextListener"
    onUnsubscribe = "onUnsubscribe"
    onDisconnect = "onDisconnect"
