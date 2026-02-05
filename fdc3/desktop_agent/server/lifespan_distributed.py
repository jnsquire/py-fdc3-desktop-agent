# Lifespan helpers for distributed adapter setup

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ..core import core_services
from ..distributed.adapter import DistributedLogAdapter
from ..distributed.factory import get_adapter
from ..tools import create_task_safe

if TYPE_CHECKING:
    from ..config import DesktopAgentConfig

logger = logging.getLogger(__name__)


async def _setup_distributed_adapter(
    config: DesktopAgentConfig,
) -> tuple[DistributedLogAdapter | None, str | None]:
    adapter = config.distributed_adapter
    if adapter is None:
        try:
            adapter = get_adapter()
        except Exception:
            logger.exception("Error creating distributed adapter")
            adapter = None

    if not adapter:
        return None, None

    try:
        await adapter.start()

        async def _distributed_event_handler(ev: Any) -> None:
            try:
                if isinstance(ev, str):
                    payload = json.loads(ev)
                else:
                    payload = ev
                core_services.channel_manager._emit_event(
                    payload.get("event_type"),
                    payload.get("channel_id"),
                    payload.get("instance_uuid"),
                    (
                        json.loads(payload.get("context"))
                        if payload.get("context")
                        else None
                    ),
                    remote=True,
                )
            except Exception:
                logger.exception("Error handling distributed event")

        def _sub_cb(ev: dict) -> None:
            # Fire-and-forget: schedule handler safely so exceptions
            # are logged instead of being dropped.
            create_task_safe(_distributed_event_handler(ev))

        sub_id = await adapter.subscribe("channel_events", _sub_cb)
        return adapter, sub_id
    except Exception:
        logger.exception("Error starting distributed adapter")
        return None, None
