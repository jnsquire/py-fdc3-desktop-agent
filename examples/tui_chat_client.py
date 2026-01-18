"""TUI chat client demo for the FDC3 desktop agent.

This example connects as a named user, joins a public user channel, and
allows you to broadcast chat messages. It also supports private channels
via invitations.

Usage:
    python examples/tui_chat_client.py --name alice --channel demo
    python examples/tui_chat_client.py --name bob --channel demo

Commands:
    /help
    /join <user-channel>
    /leave
    /pcreate [display-name]
    /pinvite <private-channel-id> [instance-id]
    /pjoin <private-channel-id> <invite-token>
    /pleave <private-channel-id>
    /quit

Notes:
    - Public channels use the "user:" prefix (added automatically).
    - Private invites can be bound to a specific instance-id, but if omitted
      any client can use the token.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import threading

# Local imports
from typing import Callable, Optional

from fdc3.client.client import FDC3Client
from fdc3.models.dacp.dacp import BroadcastEvent

# Rich-based UI (dev dependency assumed available)
from rich.console import Console as _RichConsole
from rich.text import Text as _RichText

console = _RichConsole()


class ChatClient(FDC3Client):
    """FDC3 client with minimal DACP request/response support for chat."""


class InputReader:
    def __init__(self, loop: asyncio.AbstractEventLoop, on_change: Callable[[str], None]) -> None:
        self.queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._on_change = on_change
        self._start(loop)

    def _start(self, loop: asyncio.AbstractEventLoop) -> None:
        def _worker() -> None:
            buffer: list[str] = []
            try:
                import msvcrt
                import os
                import tempfile
                debug = os.getenv("FDC3_TUI_DEBUG") == "1"
                logfile = None
                if debug:
                    logfile = os.path.join(tempfile.gettempdir(), "fdc3_tui_keys.log")

                while True:
                    ch = msvcrt.getwch()
                    if debug and logfile:
                        try:
                            with open(logfile, "a", encoding="utf-8") as fh:
                                fh.write(repr(ch) + "\n")
                        except Exception:
                            pass

                    # Enter handling: Ctrl+Enter => send, otherwise newline
                    if ch in ("\r", "\n"):
                        try:
                            import ctypes
                            ctrl_state = ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000
                            ctrl_down = bool(ctrl_state)
                        except Exception:
                            ctrl_down = False

                        if ctrl_down:
                            line = "".join(buffer)
                            buffer.clear()
                            loop.call_soon_threadsafe(self._on_change, "")
                            loop.call_soon_threadsafe(self.queue.put_nowait, line)
                        else:
                            buffer.append("\n")
                            loop.call_soon_threadsafe(self._on_change, "".join(buffer))

                        continue

                    # Ctrl+C -> quit
                    if ch == "\x03":
                        loop.call_soon_threadsafe(self.queue.put_nowait, None)
                        break

                    # Backspace
                    if ch in ("\b", "\x7f"):
                        if buffer:
                            buffer.pop()
                            loop.call_soon_threadsafe(self._on_change, "".join(buffer))
                        continue

                    # Printable chars
                    if ch.isprintable():
                        buffer.append(ch)
                        loop.call_soon_threadsafe(self._on_change, "".join(buffer))
                        continue
            except Exception:
                while True:
                    line = sys.stdin.readline()
                    if line == "":
                        loop.call_soon_threadsafe(self.queue.put_nowait, None)
                        break
                    loop.call_soon_threadsafe(self.queue.put_nowait, line.rstrip("\n"))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()


class MessageStore:
    def __init__(self) -> None:
        self._messages: list[dict] = []
        self._on_change = None

    def set_on_change(self, callback) -> None:
        self._on_change = callback

    def add(self, channel: str, sender: str, text: str, local: bool = False) -> None:
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        self._messages.append(
            {
                "time": ts,
                "channel": channel,
                "sender": sender,
                "text": text,
                "local": local,
            }
        )
        if len(self._messages) > 500:
            del self._messages[0 : len(self._messages) - 500]

        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass

    def recent(self, limit: int = 200) -> list[dict]:
        return self._messages[-limit:]


class LiveUI:
    def __init__(
        self,
        console: _RichConsole,
        store: MessageStore,
        channel_id_getter,
        input_text_getter: Callable[[], str],
    ) -> None:
        self.console = console
        self.store = store
        self._channel_id_getter = channel_id_getter
        self._input_text_getter = input_text_getter
        self.live = None

    def render(self):
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        from rich.layout import Layout

        tbl = Table.grid(expand=True)
        tbl.add_column(width=9, no_wrap=True)
        tbl.add_column(width=20, no_wrap=True)
        tbl.add_column(ratio=1)
        for msg in self.store.recent():
            time = msg.get("time", "")
            channel = msg.get("channel", "")
            sender = msg.get("sender", "")
            text = msg.get("text", "")
            tbl.add_row(f"{time}", f"[{channel}] {sender}", text)

        footer = f"Channel: {self._channel_id_getter() or '?'} — Type /help | /quit"
        messages_panel = Panel(tbl, title="Messages", subtitle=footer, expand=True)
        input_text = Text(f"> {self._input_text_getter()}", style="bold green")
        input_panel = Panel(input_text, title="", expand=True, padding=(0,1))

        layout = Layout()
        input_lines = max(1, self._input_text_getter().count("\n") + 1)
        input_size = min(max(2, input_lines + 1), 12)

        layout.split_column(
            Layout(messages_panel, ratio=1),
            Layout(input_panel, size=input_size),
        )
        return layout

    def update(self) -> None:
        if self.live is not None:
            self.live.update(self.render())

    def start(self):
        from rich.live import Live

        return Live(
            self.render(), console=self.console, refresh_per_second=10, screen=True
        )


class ChatTuiApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.console = console
        self.client = ChatClient(
            f"ws://{args.host}:{args.port}/ws", handler_id=args.name
        )
        self.current_channel_id: Optional[str] = None
        self.store = MessageStore()
        self.current_input: str = ""
        self.ui = LiveUI(
            self.console,
            self.store,
            self.get_current_channel_id,
            self.get_current_input,
        )
        self.store.set_on_change(self.ui.update)
        self.input_reader: Optional[InputReader] = None

    def get_current_channel_id(self) -> Optional[str]:
        return self.current_channel_id

    def get_current_input(self) -> str:
        return self.current_input

    def on_input_change(self, text: str) -> None:
        self.current_input = text
        self.ui.update()

    def status(self, message: str) -> None:
        if self.ui.live is not None:
            self.store.add("system", "status", message)
        else:
            self.console.print(_RichText(message, style="bold cyan"))

    async def connect(self) -> bool:
        connected = False
        for attempt in range(1, self.args.retries + 1):
            try:
                await self.client.connect()
                if await self.client.wait_for_handshake():
                    connected = True
                    break
                await self.client.close()
                raise RuntimeError("Handshake failed")
            except Exception as exc:
                self.status(f"Connection attempt {attempt} failed: {exc}")
                if attempt < self.args.retries:
                    await asyncio.sleep(self.args.retry_delay * attempt)
                else:
                    self.status("Max retries reached, exiting.")
                    return False
        return connected

    async def join_default_channel(self) -> None:
        try:
            join_resp = await self.client.join_user_channel(
                self.args.channel, auto_create=True
            )
            self.current_channel_id = join_resp.get("channel", {}).get("id")
            self.store.add("system", "join", f"Joined {self.current_channel_id}")
            self.store.add(
                "system", "uuid", f"Instance UUID: {self.client._instance_uuid}"
            )
        except Exception as exc:
            self.status(f"Failed to join channel: {exc}")

    def register_handlers(self) -> None:
        async def on_broadcast(evt: BroadcastEvent) -> None:
            ctx = evt.payload.context if hasattr(evt, "payload") else {}
            if not isinstance(ctx, dict) or ctx.get("type") != "fdc3.chat.message":
                return

            message = ctx.get("message")
            if not message:
                return

            text_payload = message.get("text")
            text = None
            if isinstance(text_payload, dict):
                text = text_payload.get("text/plain") or text_payload.get("text_plain")
            if not text:
                text = ctx.get("text")

            chat_room = ctx.get("chatRoom")
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
                self.store.add(channel, sender, text, local=False)

        async def on_private_event(payload: dict) -> None:
            channel = payload.get("channelId", "?")
            event_type = payload.get("eventType", "?")
            self.store.add(channel, "<private>", f"event={event_type}")

        self.client.broadcast_handlers.add(on_broadcast)
        self.client.private_channel_event_handlers.add(on_private_event)

    async def handle_command(self, line: str) -> bool:
        if line.startswith("/"):
            parts = line.split()
            cmd = parts[0].lower()

            if cmd in {"/quit", "/exit"}:
                return False

            if cmd == "/help":
                self.store.add(
                    "system",
                    "help",
                    "Commands: /join <channel> | /leave | /pcreate [name] | /pinvite <private-id> [instance-id] | /pjoin <private-id> <token> | /pleave <private-id> | /quit",
                )
                return True

            if cmd == "/join" and len(parts) >= 2:
                try:
                    join_resp = await self.client.join_user_channel(
                        parts[1], auto_create=True
                    )
                    self.current_channel_id = join_resp.get("channel", {}).get("id")
                    self.store.add(
                        "system", "join", f"Joined {self.current_channel_id}"
                    )
                except Exception as exc:
                    self.store.add("system", "error", f"Join failed: {exc}")
                return True

            if cmd == "/leave":
                try:
                    await self.client.leave_current_channel()
                    self.current_channel_id = None
                    self.store.add("system", "leave", "Left current channel")
                except Exception as exc:
                    self.store.add("system", "error", f"Leave failed: {exc}")
                return True

            if cmd == "/pcreate":
                display_name = parts[1] if len(parts) >= 2 else None
                try:
                    resp = await self.client.create_private_channel(display_name)
                    channel = resp.get("channel", {})
                    self.current_channel_id = channel.get("id")
                    self.store.add(
                        "system",
                        "pcreate",
                        f"Created private channel {self.current_channel_id}",
                    )
                except Exception as exc:
                    self.store.add(
                        "system", "error", f"Create private channel failed: {exc}"
                    )
                return True

            if cmd == "/pinvite" and len(parts) >= 2:
                channel_id = parts[1]
                instance_id = parts[2] if len(parts) >= 3 else None
                try:
                    resp = await self.client.create_private_channel_invite(
                        channel_id, instance_id
                    )
                    token = resp.get("invitationToken")
                    self.store.add("system", "pinvite", f"Invite token: {token}")
                except Exception as exc:
                    self.store.add("system", "error", f"Invite failed: {exc}")
                return True

            if cmd == "/pjoin" and len(parts) >= 3:
                channel_id = parts[1]
                token = parts[2]
                try:
                    resp = await self.client.join_private_channel(channel_id, token)
                    self.current_channel_id = resp.get("channel", {}).get("id")
                    self.store.add(
                        "system",
                        "pjoin",
                        f"Joined private channel {self.current_channel_id}",
                    )
                except Exception as exc:
                    self.store.add("system", "error", f"Private join failed: {exc}")
                return True

            if cmd == "/pleave" and len(parts) >= 2:
                channel_id = parts[1]
                try:
                    await self.client.leave_private_channel(channel_id)
                    if self.current_channel_id == channel_id:
                        self.current_channel_id = None
                    self.store.add(
                        "system", "pleave", f"Left private channel {channel_id}"
                    )
                except Exception as exc:
                    self.store.add("system", "error", f"Private leave failed: {exc}")
                return True

            self.store.add("system", "unknown", "Unknown command. Type /help")
            return True

        if not self.current_channel_id:
            self.store.add(
                "system", "hint", "Join a channel first with /join or /pjoin"
            )
            return True

        try:
            await self.client.send_chat_message(
                line,
                self.current_channel_id,
                provider_name=self.args.name,
                auto_create_room=False,
            )
            self.store.add(self.current_channel_id, self.args.name, line, local=True)
        except Exception as exc:
            self.store.add("system", "error", f"Send failed: {exc}")
        return True

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self.input_reader = InputReader(loop, self.on_input_change)

        if not await self.connect():
            return

        self.store.add(
            "system",
            "connected",
            f"Connected as {self.args.name} (instanceUuid={self.client._instance_uuid})",
        )
        self.register_handlers()
        await self.join_default_channel()

        with self.ui.start() as live:
            self.ui.live = live
            self.store.add("system", "help", "Type /help for commands. (Enter=NL, Ctrl+Enter=Send)")
            while True:
                line = await self.input_reader.queue.get()
                if line is None:
                    break
                line = line.strip()
                if not line:
                    continue
                should_continue = await self.handle_command(line)
                if not should_continue:
                    break

        self.status("Goodbye")
        try:
            await self.client.close()
        except Exception:
            pass


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
    from textual.widgets import Header, Footer, TextLog, Input
    try:
        from textual.widgets import TextArea as TextAreaWidget
    except Exception:
        TextAreaWidget = None

    class _TextualChatApp(App):
        CSS = """
        Screen {
            align: center middle;
        }
        #messages {
            height: 1fr;
        }
        #input {
            height: auto;
        }
        """

        BINDINGS = [("ctrl+enter", "send", "Send message")]

        def __init__(self, args: argparse.Namespace) -> None:
            super().__init__()
            self.args = args
            self.client = ChatClient(f"ws://{args.host}:{args.port}/ws", handler_id=args.name)
            self.channel_id = None

        async def compose(self):
            yield Header()
            yield TextLog(id="messages")
            if TextAreaWidget is not None:
                yield TextAreaWidget(id="input")
            else:
                yield Input(id="input")
            yield Footer()

        async def on_mount(self) -> None:
            messages = self.query_one("#messages", TextLog)
            await self.client.connect()
            if not await self.client.wait_for_handshake():
                messages.write("Handshake failed")
                await self.client.close()
                return
            join_resp = await self.client.join_user_channel(self.args.channel, auto_create=True)
            self.channel_id = join_resp.get("channel", {}).get("id")
            messages.write(f"Joined {self.channel_id}")

            async def on_broadcast(evt: BroadcastEvent) -> None:
                ctx = evt.payload.context if hasattr(evt, "payload") else {}
                if not isinstance(ctx, dict):
                    return
                if ctx.get("type") != "fdc3.chat.message":
                    return
                message = ctx.get("message") if isinstance(ctx, dict) else None
                text_payload = message.get("text") if isinstance(message, dict) else None
                text = None
                if isinstance(text_payload, dict):
                    text = text_payload.get("text/plain") or text_payload.get("text_plain")
                if not text:
                    text = ctx.get("text") if isinstance(ctx, dict) else None

                chat_room = ctx.get("chatRoom") if isinstance(ctx, dict) else None
                channel_id = None
                if isinstance(chat_room, dict):
                    room_id = chat_room.get("id") if isinstance(chat_room.get("id"), dict) else None
                    if room_id:
                        channel_id = room_id.get("channelId")
                channel = channel_id or ctx.get("channelId") or "?"
                sender = (chat_room or {}).get("providerName", "?") if isinstance(chat_room, dict) else "?"

                if text:
                    messages.write(f"[{channel}] {sender}: {text}")

            async def on_private_event(payload: dict) -> None:
                channel = payload.get("channelId", "?")
                event_type = payload.get("eventType", "?")
                messages.write(f"[private:{channel}] event={event_type}")

            self.client.broadcast_handlers.add(on_broadcast)
            self.client.private_channel_event_handlers.add(on_private_event)

        async def action_send(self) -> None:
            input_widget = self.query_one("#input")
            text = getattr(input_widget, "value", "")
            if not text or not text.strip():
                return
            await self.client.send_chat_message(text, self.channel_id, provider_name=self.args.name, auto_create_room=False)
            self.query_one("#messages", TextLog).write(f"{self.args.name}: {text}")
            # clear input
            try:
                input_widget.value = ""
            except Exception:
                pass

    app = _TextualChatApp(args)
    app.run()
    return


if __name__ == "__main__":
    asyncio.run(main())
