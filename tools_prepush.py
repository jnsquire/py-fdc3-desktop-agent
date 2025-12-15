"""Pre-push style checks runner (standalone module).

This module is intentionally top-level (not inside the package) so it can
be executed without importing `fdc3_desktop_agent` and triggering app
initialization side-effects.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Sequence


def _run(cmd: Sequence[str]) -> int:
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd)
    return res.returncode


def prepush() -> None:
    """Run ruff and black checks used by CI.

    Exits with non-zero status if any check fails.
    """
    cmds = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "black", "--check", "."],
    ]

    failures = 0
    for cmd in cmds:
        rc = _run(cmd)
        if rc != 0:
            failures += 1

    if failures:
        print(f"Style checks failed ({failures} failed). Fix issues and try again.")
        raise SystemExit(1)


if __name__ == "__main__":
    prepush()
