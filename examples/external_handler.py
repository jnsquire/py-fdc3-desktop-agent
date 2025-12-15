"""Example external intent handler using the `fdc3.client` library.

Usage:

    python -m examples.external_handler --agent-url ws://localhost:8000/ws

This connects, performs WCP handshake, registers a handler for a test intent,
and replies with a simple payload.
"""

import argparse
import asyncio
import sys
import logging

from fdc3.client import FDC3Client

logger = logging.getLogger(__name__)


async def main(agent_url: str, handler_id: str):
    # Create client with handler_id for WCP self-registration
    async with FDC3Client(agent_url, handler_id=handler_id) as client:

        async def on_intent(request):
            logger.info(f"Received intent: {request.intent} id={request.request_uuid}")
            # Simple handling: echo the context back with handler info
            await client.send_intent_result(
                request.request_uuid,
                result={
                    "handledBy": handler_id,
                    "intent": request.intent,
                    "context": getattr(request, "context", {}),
                },
            )

        client.on_intent(on_intent)

        # Wait for WCP handshake to complete
        if not await client.wait_for_handshake():
            logger.error("WCP handshake failed, exiting")
            return

        # Register handler for intents
        try:
            handler_uuid = await client.register_handler(
                handler_id, ["Example.Intent", "ViewChart"], priority=5
            )
            logger.info(f"Registered handler {handler_uuid} for intents")
        except Exception:
            logger.exception("Failed to register handler")
            return

        # Set up signal handlers for graceful shutdown (Unix only)
        stop = asyncio.Event()

        if sys.platform != "win32":
            import signal

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
        else:
            # On Windows, just wait for keyboard interrupt
            logger.info("Press Ctrl+C to stop")

        try:
            await stop.wait()
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass

        # Graceful unregister
        try:
            await client.unregister_handler(handler_uuid)
            logger.info(f"Unregistered handler {handler_uuid}")
        except Exception:
            logger.debug("Failed to unregister (connection may be closed)")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    p = argparse.ArgumentParser(description="Example external intent handler")
    p.add_argument(
        "--agent-url", default="ws://localhost:8000/ws", help="Agent WebSocket URL"
    )
    p.add_argument(
        "--handler-id", default="example-handler", help="Handler ID for registration"
    )
    args = p.parse_args()
    asyncio.run(main(args.agent_url, args.handler_id))
