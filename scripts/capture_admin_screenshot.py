"""Capture an Admin UI screenshot for documentation.

Usage:
  python scripts/capture_admin_screenshot.py --output documentation/assets/admin-ui-preview.png

Notes:
  - Requires Playwright: pip install playwright
  - One-time browser install: python -m playwright install
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright


DEFAULT_URL = "http://127.0.0.1:8000/admin"


def _wait_for_admin(url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return
        except Exception as exc:  # pragma: no cover - best effort wait
            last_error = exc
        time.sleep(0.5)
    if last_error:
        raise RuntimeError(f"Admin UI not reachable: {last_error}")
    raise RuntimeError("Admin UI not reachable before timeout")


def _start_server() -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.setdefault("FDC3_ALLOWED_ORIGINS", "*")
    env.setdefault("FDC3_HOST", "127.0.0.1")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "fdc3.desktop_agent.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    return subprocess.Popen(cmd, env=env)


def _stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Admin UI screenshot")
    parser.add_argument("--output", default="documentation/assets/admin-ui-preview.png")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--viewport", default="1280x720")
    args = parser.parse_args()

    width, height = (int(value) for value in args.viewport.lower().split("x"))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    server: subprocess.Popen[str] | None = None
    try:
        try:
            _wait_for_admin(args.url, timeout_seconds=3.0)
        except RuntimeError:
            server = _start_server()
            _wait_for_admin(args.url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(args.url, wait_until="networkidle")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(output_path), full_page=True)
            browser.close()
    finally:
        if server is not None:
            _stop_server(server)

    print(f"Saved screenshot to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
