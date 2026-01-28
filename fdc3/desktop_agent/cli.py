"""Command-line stub to launch the FDC3 Desktop Agent.

Invokes uvicorn (or uv run uvicorn) in a subprocess and forwards
Ctrl-C / SIGTERM so shutdown logs complete before the shell prompt returns.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
from typing import List, Optional


def _terminate_child(proc: subprocess.Popen) -> None:
    """Send the appropriate stop signal to *proc* (platform-specific)."""
    try:
        if os.name == "nt":
            # On Windows, terminate() sends SIGTERM equivalent
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def _build_command(argv: List[str]) -> Optional[List[str]]:
    """Return the command list to launch uvicorn, or None if unavailable."""
    # Prefer `uv` module if available, otherwise fall back to `uvicorn`.
    if importlib.util.find_spec("uv") is not None:
        return [sys.executable, "-m", "uv"] + list(argv)

    if importlib.util.find_spec("uvicorn") is not None:
        # Normalize "run uvicorn ..." style argv to plain uvicorn args.
        if len(argv) >= 2 and argv[0] == "run" and argv[1] == "uvicorn":
            uvicorn_args = argv[2:]
        else:
            uvicorn_args = argv
        return [sys.executable, "-m", "uvicorn"] + list(uvicorn_args)

    return None


async def _register_app(json_path: str) -> int:
    import json
    from fdc3.desktop_agent.storage import SqliteStorage, AppMetadata, LaunchConfig
    from fdc3.desktop_agent.config import DesktopAgentConfig

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file {json_path}: {e}")
        return 1

    config = DesktopAgentConfig()
    storage = SqliteStorage(config.db_path)
    await storage.initialize()

    try:
        app_id = data.get("appId") or data.get("app_id")
        if not app_id:
            print("Error: 'appId' is required in the JSON file.")
            return 1

        metadata = AppMetadata(
            app_id=app_id,
            name=data.get("name") or data.get("title") or app_id,
            version=data.get("version", ""),
            description=data.get("description", ""),
            icons=data.get("icons", []),
            intents=[
                i if isinstance(i, str) else i.get("name")
                for i in data.get("intents", [])
                if isinstance(i, str) or (isinstance(i, dict) and i.get("name"))
            ],
            allowed_origins=data.get("allowedOrigins")
            or data.get("allowed_origins", []),
        )
        await storage.apps.add_app(metadata)

        launch_data = data.get("launch")
        if launch_data:
            launch_config = LaunchConfig(
                app_id=app_id,
                command=launch_data.get("command", ""),
                args=launch_data.get("args", []),
                env=launch_data.get("env", {}),
                cwd=launch_data.get("cwd", ""),
                timeout=launch_data.get("timeout", 30),
            )
            await storage.launch_configs.set_launch_config(launch_config)

        print(f"Successfully registered app '{app_id}' in {config.db_path}")
        return 0
    except Exception as e:
        print(f"Error registering app: {e}")
        return 1
    finally:
        await storage.close()


async def _list_apps() -> int:
    from fdc3.desktop_agent.storage import SqliteStorage
    from fdc3.desktop_agent.config import DesktopAgentConfig

    config = DesktopAgentConfig()
    storage = SqliteStorage(config.db_path)
    await storage.initialize()

    try:
        apps = await storage.apps.list_apps()
        if not apps:
            print(f"No apps registered in {config.db_path}")
            return 0

        print(f"Apps registered in {config.db_path}:")
        for app in apps:
            print(f" - {app.app_id} ({app.name})")
        return 0
    finally:
        await storage.close()


async def _remove_app(app_id: str) -> int:
    from fdc3.desktop_agent.storage import SqliteStorage
    from fdc3.desktop_agent.config import DesktopAgentConfig

    config = DesktopAgentConfig()
    storage = SqliteStorage(config.db_path)
    await storage.initialize()

    try:
        await storage.apps.remove_app(app_id)
        await storage.launch_configs.remove_launch_config(app_id)
        print(f"Removed app '{app_id}' and its launch config from {config.db_path}")
        return 0
    finally:
        await storage.close()


def main(argv: List[str] | None = None) -> int:
    """Launch the desktop agent or manage the app directory.

    If no arguments are provided, starts uvicorn in dev mode with reload.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Handle management subcommands
    if argv and argv[0] in ("register-app", "list-apps", "remove-app"):
        import argparse
        import asyncio

        parser = argparse.ArgumentParser(
            prog="fdc3-agent", description="FDC3 App Directory Management"
        )
        subparsers = parser.add_subparsers(dest="command")

        reg_parser = subparsers.add_parser(
            "register-app", help="Register an app from JSON definition"
        )
        reg_parser.add_argument(
            "json_file", help="Path to the JSON file containing app metadata"
        )

        subparsers.add_parser("list-apps", help="List all registered apps")

        rem_parser = subparsers.add_parser("remove-app", help="Remove an app by its ID")
        rem_parser.add_argument("app_id", help="The appId to remove")

        args = parser.parse_args(argv)

        if args.command == "register-app":
            return asyncio.run(_register_app(args.json_file))
        elif args.command == "list-apps":
            return asyncio.run(_list_apps())
        elif args.command == "remove-app":
            return asyncio.run(_remove_app(args.app_id))

    if not argv:
        argv = [
            "run",
            "uvicorn",
            "fdc3.desktop_agent.server:app",
            "--reload",
            "--host",
            "localhost",
            "--port",
            "8000",
        ]

    cmd = _build_command(argv)
    if cmd is None:
        print(
            "Neither `uv` nor `uvicorn` is installed. Install one of them first.",
            file=sys.stderr,
        )
        return 2

    # On Unix, start_new_session gives a new process group for clean signal handling.
    # On Windows, we do NOT use CREATE_NEW_PROCESS_GROUP so that Ctrl-C naturally
    # propagates to both parent and child via the shared console.
    popen_kwargs: dict = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True

    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
        return proc.wait()
    except KeyboardInterrupt:
        # Forward the interrupt to the child and wait for clean shutdown.
        if proc is not None and proc.poll() is None:
            _terminate_child(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        return 0
    except FileNotFoundError:
        print("Runner not found. Ensure uv or uvicorn is installed.", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"Failed to launch FDC3 Desktop Agent: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
