"""ViewChart-only external intent handler example.

This example registers for the `ViewChart` intent and, when invoked, will
attempt to extract a ticker/symbol from the forwarded context and open a
chart in the system browser (optional). It always replies to the agent with
an `intentResult` containing a `chartUrl` and the extracted symbol (if any).

Usage:

    python -m examples.external_handler_viewchart --agent-url ws://localhost:8000/ws --handler-id viewchart-handler --open

Command line options:
  --agent-url   WebSocket URL of the agent (default: ws://localhost:8000/ws)
  --handler-id  Handler id used for registration (default: viewchart-handler)
  --open        If present, open the chart URL in the system browser

"""

import argparse
import asyncio
import json
import logging
import sys
import webbrowser
from typing import Any, Dict, Optional

from fdc3.client import FDC3Client
from fdc3.models.dacp import ForwardedIntentMessage

logger = logging.getLogger(__name__)


def extract_symbol_from_context(context: Dict[str, Any]) -> Optional[str]:
    # Try common places where an instrument ticker might appear
    # e.g. {"id": "AAPL", "ticker":"AAPL"} or nested
    if not context:
        return None

    # common top-level keys
    for key in ("id", "ticker", "symbol", "ric", "name"):
        if key in context and isinstance(context[key], str):
            return context[key]

    # sometimes context has an "data" field
    data = context.get("data")
    if isinstance(data, dict):
        for key in ("id", "ticker", "symbol", "ric", "name"):
            if key in data and isinstance(data[key], str):
                return data[key]

    return None


async def main(agent_url: str, handler_id: str, open_browser: bool):
    async with FDC3Client(agent_url, handler_id=handler_id) as client:

        async def on_intent(request: ForwardedIntentMessage):
            payload = request.payload
            req_id = payload.request_uuid
            intent = payload.intent
            context = payload.context or {}

            logger.info("Received forwarded intent %s id=%s", intent, req_id)

            # We're focused on ViewChart only
            if intent.lower() != "viewchart":
                logger.warning("Unexpected intent %s, ignoring", intent)
                await client.send_intent_result(req_id, error="NotHandledByThisHandler")
                return

            symbol = extract_symbol_from_context(context)
            if symbol:
                # Simple chart URL using Google search for a chart (keeps example dependency-free)
                chart_url = f"https://www.google.com/search?q={symbol}+chart"
            else:
                chart_url = ""

            # Optionally open in system browser for demo purposes
            if open_browser and chart_url:
                try:
                    webbrowser.open(chart_url)
                except Exception:
                    logger.exception("Failed to open browser for %s", chart_url)

            # Reply with a structured result
            result = {"handledBy": handler_id, "chartUrl": chart_url, "symbol": symbol}
            await client.send_intent_result(req_id, result=result)

            logger.info(
                "Responded to %s id=%s result=%s", intent, req_id, json.dumps(result)
            )

        client.forwarded_intent_handlers.add(on_intent)

        # Wait for WCP handshake to complete
        if not await client.wait_for_handshake():
            logger.error("WCP handshake failed, exiting")
            return

        # Register for ViewChart only
        try:
            handler_uuid = await client.register_handler(
                handler_id, ["ViewChart"], priority=5
            )
            logger.info("Registered handler %s for ViewChart", handler_uuid)
        except Exception:
            logger.exception("Failed to register handler")
            return

        # Run until interrupted
        stop = asyncio.Event()

        if sys.platform != "win32":
            import signal

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
        else:
            logger.info("Press Ctrl+C to stop")

        try:
            await stop.wait()
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass

        # Unregister on exit
        try:
            await client.unregister_handler(handler_uuid)
            logger.info("Unregistered handler %s", handler_uuid)
        except Exception:
            logger.debug("Failed to unregister (connection may be closed)")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    p = argparse.ArgumentParser(description="ViewChart external intent handler example")
    p.add_argument(
        "--agent-url", default="ws://localhost:8000/ws", help="Agent WebSocket URL"
    )
    p.add_argument(
        "--handler-id", default="viewchart-handler", help="Handler ID for registration"
    )
    p.add_argument(
        "--open",
        action="store_true",
        help="Open the chart URL in the system browser when handling",
    )
    args = p.parse_args()
    asyncio.run(main(args.agent_url, args.handler_id, args.open))
