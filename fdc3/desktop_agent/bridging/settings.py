from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from fdc3.desktop_agent.config import DesktopAgentConfig


@dataclass(init=False)
class BridgeConnectionSettings:
    host: str
    port_start: int
    port_end: int
    requested_name: str
    retry_seconds: float
    request_timeout_seconds: float

    @overload
    def __init__(self, config: "DesktopAgentConfig") -> None: ...

    @overload
    def __init__(
        self,
        *,
        host: str,
        port_start: int,
        port_end: int,
        requested_name: str,
        retry_seconds: float,
        request_timeout_seconds: float,
    ) -> None: ...

    def __init__(
        self,
        config: "DesktopAgentConfig | None" = None,
        *,
        host: str | None = None,
        port_start: int | None = None,
        port_end: int | None = None,
        requested_name: str | None = None,
        retry_seconds: float | None = None,
        request_timeout_seconds: float | None = None,
    ) -> None:
        if config is not None:
            self.host = config.bridge_host
            self.port_start = config.bridge_port_start
            self.port_end = config.bridge_port_end
            self.requested_name = config.bridge_requested_name
            self.retry_seconds = config.bridge_connect_retry_seconds
            self.request_timeout_seconds = config.bridge_request_timeout_seconds
            return

        if (
            host is None
            or port_start is None
            or port_end is None
            or requested_name is None
            or retry_seconds is None
            or request_timeout_seconds is None
        ):
            raise TypeError("Missing bridge connection settings")

        self.host = host
        self.port_start = port_start
        self.port_end = port_end
        self.requested_name = requested_name
        self.retry_seconds = retry_seconds
        self.request_timeout_seconds = request_timeout_seconds
