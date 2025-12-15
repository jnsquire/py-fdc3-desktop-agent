"""Utility scripts for developer workflows.

Provide a `prepush`/`check_style` entry point that runs the same style
and lint checks used by CI so contributors can run them locally.
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
    cmds = [[sys.executable, "-m", "ruff", "check", "."]]

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


def install_git_hooks() -> None:
    """Install `pre-commit` and register git hooks.

    Installs into the active Python environment (venv) when detected,
    otherwise falls back to a user install.
    """
    python = sys.executable
    print(f"Using Python executable: {python}")

    inside_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if inside_venv:
        rc = _run([python, "-m", "pip", "install", "pre-commit"])
    else:
        rc = _run([python, "-m", "pip", "install", "--user", "pre-commit"])

    if rc != 0:
        print("Failed to install pre-commit; aborting.")
        raise SystemExit(1)

    rc = _run([python, "-m", "pre_commit", "install"])
    if rc != 0:
        print(
            "pre-commit install failed. You may need to run 'pre-commit install' manually."
        )
        raise SystemExit(1)

    print("pre-commit hooks installed. Run: pre-commit run --all-files")
