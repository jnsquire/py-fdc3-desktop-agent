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


def main(argv: List[str] | None = None) -> int:
    """Launch the desktop agent.

    If no arguments are provided, starts uvicorn in dev mode with reload.
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        argv = [
            "run",
            "uvicorn",
            "fdc3_desktop_agent.server:app",
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
