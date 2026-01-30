"""TUI chat client demo for the FDC3 desktop agent.

This example connects as a named user, joins a public user channel, and
allows you to broadcast chat messages. It also supports private channels
via invitations. The UI is implemented with Textual.

Usage:
    python examples/tui_chat_client.py --name alice --channel demo
    python examples/tui_chat_client.py --name bob --channel demo

Controls:
    Enter: send message
    Shift+Enter or Ctrl+N: insert newline (Shift+Enter may not be distinguishable in some terminals)

Notes:
    - Public channels use the "user:" prefix (added automatically).
    - Private invites can be bound to a specific instance-id, but if omitted
        any client can use the token.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Callable, Coroutine, Optional, Protocol, TypeVar, cast

from fdc3.client.client import FDC3Client
from fdc3.models.dacp.dacp import BroadcastEvent

_TWidget = TypeVar("_TWidget")


def cached_widget(
    selector: str, widget_type: type[_TWidget]
) -> Callable[[Callable[..., _TWidget]], property]:
    """Decorator to cache Textual widget lookups on first access.

    The decorated function body can be empty; the decorator performs the lookup.
    """

    def decorator(func: Callable[..., _TWidget]) -> property:
        name = getattr(func, "__name__", "widget")
        cache_attr = f"__cached_{name}"

        @property
        def wrapper(self: Any) -> _TWidget:
            cached = getattr(self, cache_attr, None)
            if cached is None:
                cached = self.query_one(selector, widget_type)
                setattr(self, cache_attr, cached)
            return cached

        return wrapper

    return decorator


async def main() -> None:
    parser = argparse.ArgumentParser(description="FDC3 TUI chat client")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--name", required=True, help="User name / handler id")
    parser.add_argument("--channel", default="demo", help="User channel to join")
    parser.add_argument(
        "--retries", type=int, default=5, help="Number of connect retries"
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.0,
        help="Base delay between retries in seconds",
    )
    args = parser.parse_args()

    # Run the Textual TUI (Textual is a dev dependency and assumed present)
    from textual.app import App
    from textual.binding import Binding
    from textual.widgets import Header, Footer, Input

    # Prefer Log + TextArea widgets
    from textual.widgets import Log, TextArea

    class _SendApp(Protocol):
        def action_send(self) -> Coroutine[Any, Any, None]: ...

    # Subclass TextArea to intercept Enter (without Shift) to send the message.
    class ChatTextArea(TextArea):
        BINDINGS = [
            Binding("enter", "send", "Send", priority=True, show=False),
            Binding("ctrl+n", "newline", "Newline", show=False),
            Binding("shift+enter", "newline", "Newline", show=False),
        ]

        def action_send(self) -> None:
            """Send on Enter (priority binding).

            Attempts to schedule the send action using Textual's call_later if available,
            otherwise falls back to creating a task directly. Errors are logged in _safe_send.
            """
            app = cast(_SendApp, self.app)
            # Try to use Textual's call_later for proper event loop integration
            if hasattr(self.app, "call_later"):
                try:
                    self.app.call_later(
                        lambda: asyncio.create_task(self._safe_send(app))
                    )
                    return
                except RuntimeError:
                    # call_later may fail if the app is not fully initialized or shutting down
                    pass

            # Fallback: create task directly (may not integrate as well with Textual's event loop)
            try:
                asyncio.create_task(self._safe_send(app))
            except RuntimeError:
                # Event loop may not be running; task creation failed
                pass

        def action_newline(self) -> None:
            """Insert a newline on Ctrl+N (fallback when Shift+Enter isn't distinguishable).

            Silently ignores errors if the widget is read-only or not editable.
            """
            try:
                self.insert("\n")
            except (AttributeError, RuntimeError, ValueError):
                # Widget may be read-only, not editable, or in an invalid state
                pass

        async def _safe_send(self, app: _SendApp) -> None:
            """Safely execute the send action and log any errors.

            This wrapper ensures that send failures are caught and displayed to the user
            in the message log. If logging fails, the error is silently ignored to avoid
            cascading failures.
            """
            try:
                await app.action_send()
            except Exception as exc:
                # Attempt to log the error to the messages widget
                self._log_error(f"Send failed: {exc}")

        def _log_error(self, message: str) -> None:
            """Log an error message to the messages widget.

            Silently ignores failures to prevent cascading errors during error handling.
            """
            try:
                self.app.query_one("#messages", Log).write_line(message)
            except (AttributeError, RuntimeError, LookupError):
                # Failed to access the messages widget (app may be shutting down or widget not found)
                pass

    TextAreaWidget = ChatTextArea

    class _TextualChatApp(App):
        TITLE = "FDC3 Chat Client"
        CSS = """
        Screen {
            align: center middle;
        }
        #messages {
            height: 1fr;
            border: tall $secondary;
            padding: 0 1;
        }
        #input {
            height: auto;
        }
        """

        # No global bindings; input widget handles Enter/Shift+Enter
        BINDINGS = []

        def __init__(self, args: argparse.Namespace) -> None:
            super().__init__()
            self.args = args
            self.client = FDC3Client(
                f"ws://{args.host}:{args.port}/ws", handler_id=args.name
            )
            self.channel_id: Optional[str] = None

        @cached_widget("#messages", Log)
        def messages(self) -> Log:
            raise NotImplementedError

        @cached_widget("#input", TextArea)
        def input_widget(self) -> TextArea:
            raise NotImplementedError

        def compose(self):
            # Return a concrete list of widgets (avoid generator which can be misinterpreted as async)
            widgets = [Header(), Log(id="messages", auto_scroll=True, max_lines=1000)]
            # TextArea supports multiline editing; Input is single-line fallback
            if TextAreaWidget is not None:
                widgets.append(TextAreaWidget(id="input"))
            else:
                widgets.append(Input(id="input"))
            widgets.append(Footer())
            return widgets

        async def on_mount(self) -> None:
            messages = self.messages
            await self.client.connect()
            if not await self.client.wait_for_handshake():
                messages.write_line("Handshake failed")
                await self.client.close()
                return
            try:
                self.input_widget.focus()
            except Exception:
                pass
            join_resp = await self.client.join_user_channel(
                self.args.channel, auto_create=True
            )
            # join_resp may be a JoinUserChannelResponse model or dict
            if hasattr(join_resp, "payload"):
                channel = getattr(join_resp.payload, "channel", None)
                self.channel_id = getattr(channel, "id", None) if channel else None
            else:
                self.channel_id = join_resp.get("channel", {}).get("id")
            messages.write_line(f"Joined {self.channel_id}")
            # Short help for key bindings
            messages.write_line("Send: Enter | Newline: Shift+Enter or Ctrl+N")

            async def on_broadcast(evt: BroadcastEvent) -> None:
                ctx = evt.payload.context if hasattr(evt, "payload") else {}
                if not isinstance(ctx, dict):
                    return
                if ctx.get("type") != "fdc3.chat.message":
                    return
                message = ctx.get("message") if isinstance(ctx, dict) else None
                text_payload = (
                    message.get("text") if isinstance(message, dict) else None
                )
                text = None
                if isinstance(text_payload, dict):
                    text = text_payload.get("text/plain") or text_payload.get(
                        "text_plain"
                    )
                if not text:
                    text = ctx.get("text") if isinstance(ctx, dict) else None

                chat_room = ctx.get("chatRoom") if isinstance(ctx, dict) else None
                channel_id = None
                if isinstance(chat_room, dict):
                    room_id = (
                        chat_room.get("id")
                        if isinstance(chat_room.get("id"), dict)
                        else None
                    )
                    if room_id:
                        channel_id = room_id.get("channelId")
                channel = channel_id or ctx.get("channelId") or "?"
                sender = (
                    (chat_room or {}).get("providerName", "?")
                    if isinstance(chat_room, dict)
                    else "?"
                )

                if text:
                    try:
                        lines = text.splitlines() or [""]
                        messages.write_line(f"[{channel}] {sender}: {lines[0]}")
                        for line_part in lines[1:]:
                            messages.write_line(f"    {line_part}")
                    except Exception:
                        try:
                            messages.write_line(f"[{channel}] {sender}: {text}")
                        except Exception:
                            pass

            async def on_private_event(payload: dict) -> None:
                channel = payload.get("channelId", "?")
                event_type = payload.get("eventType", "?")
                messages.write_line(f"[private:{channel}] event={event_type}")

            self.client.broadcast_handlers.add(on_broadcast)
            self.client.private_channel_event_handlers.add(on_private_event)

        async def on_unmount(self) -> None:
            try:
                await self.client.close()
            except Exception:
                pass

        async def action_send(self) -> None:
            input_widget = self.input_widget
            text = input_widget.text
            clear_fn = getattr(input_widget, "clear", None)

            if not text or not text.strip():
                return

            # Send the message (guard against missing channel id)
            if not self.channel_id:
                try:
                    self.messages.write_line("Not joined to a channel yet")
                except Exception:
                    pass
                return
            await self.client.send_chat_message(
                text,
                self.channel_id,
                provider_name=self.args.name,
                auto_create_room=False,
            )

            # Local echo of sent message
            try:
                messages = self.messages
                lines = text.splitlines() or [""]
                messages.write_line(f"[{self.channel_id}] {self.args.name}: {lines[0]}")
                for line_part in lines[1:]:
                    messages.write_line(f"    {line_part}")
            except Exception:
                pass

            # Clear using canonical clear() when available
            try:
                if callable(clear_fn):
                    clear_fn()
                else:
                    # If clear is missing, set the widget's attribute directly (best-effort)
                    input_widget.text = ""
            except Exception:
                try:
                    self.messages.write_line("Failed to clear input")
                except Exception:
                    pass

    app = _TextualChatApp(args)
    # Run Textual in a separate thread to avoid blocking the current asyncio loop
    await asyncio.to_thread(app.run)
    return


if __name__ == "__main__":
    asyncio.run(main())
