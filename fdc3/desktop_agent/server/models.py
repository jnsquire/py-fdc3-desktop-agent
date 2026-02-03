"""Shared Pydantic models for server components.

Models here are lightweight and intended for validating incoming
administrative or bridge-provided payloads (e.g. channelsState).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, RootModel


class ChannelContextItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str


class ChannelsStateModel(RootModel[dict[str, list[ChannelContextItem]]]):
    model_config = ConfigDict()
