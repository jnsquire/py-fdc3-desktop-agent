"""Common primitive Pydantic types used across DACP models.

This module hosts small RootModel wrappers for UUIDs and timestamps so
that multiple model modules can import the same definitions without
depending on the whole `desktop_agent.api` generated module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import Field, RootModel


class ConnectionAttemptUuid(RootModel[str]):
    root: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description=(
            "Unique identifier for a for an attempt to connect to a Desktop Agent. "
            "A Unique UUID should be used in the first (WCP1Hello) message and "
            "should be quoted in all subsequent messages to link them to the same connection attempt."
        ),
        title="Connection Attempt UUID",
    )


class RequestUuid(RootModel[str]):
    root: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for a request or event message. Required in all message types.",
        title="Request UUID",
    )


class ResponseUuid(RootModel[str]):
    root: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description=(
            "Unique identifier for a response to a specific message and must always be accompanied by a RequestUuid."
        ),
        title="Response UUID",
    )


class EventUuid(RootModel[str]):
    root: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for an event message sent from a Desktop Agent to an app.",
        title="Event UUID",
    )


class ListenerUuid(RootModel[str]):
    root: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description=(
            "Unique identifier for a `listener` object returned by a Desktop Agent to an app in response "
            "to addContextListener, addIntentListener or one of the PrivateChannel event listeners and used to identify it in messages (e.g. when unsubscribing)."
        ),
        title="Listener UUID",
    )


class Timestamp(RootModel[str]):
    root: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Timestamp at which the message was generated.",
        title="Timestamp",
    )


# Generic ErrorMessages left in the generated api module; include alias if needed
# Re-export type name for convenience
__all__ = [
    "ConnectionAttemptUuid",
    "RequestUuid",
    "ResponseUuid",
    "EventUuid",
    "ListenerUuid",
    "Timestamp",
]
