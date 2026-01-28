from __future__ import annotations
from typing import Protocol, runtime_checkable
from pydantic import BaseModel


@runtime_checkable
class MessageSender(Protocol):
    """Protocol for sending DACP messages to a connected client."""

    async def send_model(self, model: BaseModel) -> None:
        """Send a Pydantic model as a message."""
        ...
