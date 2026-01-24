"""Shared Pydantic types for desktop agent handlers."""

from __future__ import annotations

from typing import Any, Dict, Mapping, TypeAlias

from pydantic import BaseModel, ConfigDict


class WcpIdentity(BaseModel):
    model_config = ConfigDict(extra="allow")

    appId: str | None = None
    instanceId: str | None = None
    instanceUuid: str | None = None


class WcpSession(BaseModel):
    model_config = ConfigDict(extra="allow")

    identity: WcpIdentity | None = None
    wcp1_identity: dict[str, Any] | None = None
    state: str | None = None


WcpSessions: TypeAlias = Dict[str, WcpSession]


class IntentEntryMapping(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    intent: str | None = None
    intentName: str | None = None
    contexts: list[str] | str | None = None
    contextTypes: list[str] | str | None = None


IntentEntry: TypeAlias = str | IntentEntryMapping | Mapping[str, Any]
