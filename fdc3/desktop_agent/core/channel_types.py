from __future__ import annotations

from typing import Any, Callable, List, Optional

from pydantic import BaseModel
from typing_extensions import TypedDict

from ..api import DisplayMetadata


class ChannelEvent(TypedDict):
    event_type: str
    channel_id: str
    instance_uuid: Optional[str]
    context: Optional[str]
    timestamp: str


class EventSubscription(TypedDict):
    callback: Callable[[ChannelEvent], Any]
    channel_filter: Optional[str]


class ChannelInfo(TypedDict):
    id: str
    type: str
    display_name: Optional[str]
    color: Optional[str]
    member_count: int


class PrivateChannelInvite(BaseModel):
    token: str
    instanceId: Optional[str] = None


class PrivateChannelState(TypedDict):
    id: str
    owner: Optional[str]
    members: List[str]
    invites: List[PrivateChannelInvite]


class ChannelInstance:
    def __init__(
        self,
        channel_id: str,
        channel_type: str,
        display_metadata: Optional[DisplayMetadata] = None,
    ):
        self.id = channel_id
        self.type = channel_type
        self.display_metadata = display_metadata
        self.members: List[str] = []  # instance_uuids
