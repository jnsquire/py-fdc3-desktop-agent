"""Web endpoint launcher abstractions."""

from __future__ import annotations

import logging
import webbrowser
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class WebEndpointLauncher(ABC):
    """Interface for launching web-based endpoints."""

    @abstractmethod
    async def launch(self, url: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Launch a web endpoint URL. Returns True if launch was attempted."""
        pass


class WebBrowserLauncher(WebEndpointLauncher):
    """Default web launcher using the system browser."""

    async def launch(self, url: str, context: Optional[Dict[str, Any]] = None) -> bool:
        try:
            opened = webbrowser.open(url)
            if not opened:
                logger.warning("Web launcher did not report success for %s", url)
            return True
        except Exception as e:
            logger.error("Failed to open URL %s: %s", url, e)
            return False
