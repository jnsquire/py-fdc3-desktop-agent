from __future__ import annotations

from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from fdc3.models.identifiers import AppIdentifier

from .types import ChannelMember


class BridgeMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestUuid: Optional[str] = None
    responseUuid: Optional[str] = None
    timestamp: Optional[str] = None
    source: Optional[AppIdentifier] = None
    destination: Optional[AppIdentifier] = None


class BridgeMessage(BaseModel):
    """Generic envelope for any bridge message.

    We keep this permissive (extra fields allowed) so the client can safely
    ignore new/unknown message types while still getting typed `meta`.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    payload: Optional[dict[str, Any]] = None
    meta: Optional[BridgeMeta] = None


class BridgeHelloPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    desktopAgentBridgeVersion: str


class BridgeHello(BridgeMessage):
    type: Literal["hello"]
    payload: BridgeHelloPayload


class BridgeHandshakePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    requestedName: str
    implementationMetadata: Mapping[str, Any]
    channelsState: Mapping[str, list[ChannelMember]] = Field(default_factory=dict)


class BridgeHandshake(BridgeMessage):
    type: Literal["handshake"]
    payload: BridgeHandshakePayload
    meta: BridgeMeta


class BridgeConnectedAgentsUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    addAgent: Optional[str] = None
    allAgents: list[dict] = Field(default_factory=list)
    channelsState: Optional[Mapping[str, list[dict[str, Any]]]] = None


class BridgeConnectedAgentsUpdate(BridgeMessage):
    type: Literal["connectedAgentsUpdate"]
    payload: BridgeConnectedAgentsUpdatePayload
    meta: Optional[BridgeMeta] = None


class BridgeAuthenticationFailedPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: Optional[str] = None


class BridgeAuthenticationFailed(BridgeMessage):
    type: Literal["authenticationFailed"]
    payload: Optional[BridgeAuthenticationFailedPayload] = None
