from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping, Optional, Union

from typing_extensions import NotRequired, TypedDict
from websockets.asyncio.client import ClientConnection

from fdc3.models.identifiers import AppIdentifier, BaseImplementationMetadata

ConnectFunc = Callable[[str], Awaitable[ClientConnection]]

# Type alias for implementation metadata return type
ImplementationMetadata = Mapping[str, Any] | BaseImplementationMetadata

# Factory type alias for implementation metadata
ImplementationMetadataFactory = Callable[[], ImplementationMetadata]

# Type alias for AppIdentifier or dict representation
AppIdentifierLike = Union[AppIdentifier, dict[str, Any]]


class ChannelMember(TypedDict):
    """A channel member entry for the bridging handshake channels state."""

    desktopAgent: str
    instanceUuid: str
    appId: NotRequired[str]
    instanceId: NotRequired[str]


# Type alias for the full channels state mapping
ChannelsState = Mapping[str, list[ChannelMember]]


# Factory type alias for channels state
ChannelsStateFactory = Callable[[], ChannelsState]


# Type alias for request handler
RequestHandler = Callable[[Mapping[str, Any]], Awaitable[Optional[Mapping[str, Any]]]]


class BridgeResponseMetaDict(TypedDict, total=False):
    """Metadata from a bridge response (dict form)."""

    requestUuid: str
    responseUuid: str
    timestamp: str
    errorSources: list[str]
    errorDetails: list[dict[str, Any]]


class BridgeResponseDict(TypedDict, total=False):
    """Response structure from bridge agent requests (dict form)."""

    type: str
    meta: BridgeResponseMetaDict
    payload: dict[str, Any]
