"""Utility scripts for developer workflows.

Provide a `prepush`/`check_style` entry point that runs the same style
and lint checks used by CI so contributors can run them locally.
"""

from __future__ import annotations

import subprocess
import sys
import shutil
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

    # If pre-commit is already available (importable or on PATH), skip install.
    have_pre_commit = False
    try:
        # pre-commit is an optional dev dependency; keep import local only when used

        have_pre_commit = True
    except Exception:
        if shutil.which("pre-commit"):
            have_pre_commit = True

    if not have_pre_commit:
        uv_path = shutil.which("uv")
        if uv_path:
            pip_cmd = ["uv", "pip", "install"]
        else:
            pip_cmd = [python, "-m", "pip", "install"]

        if not inside_venv:
            pip_cmd.append("--user")

        pip_cmd.append("pre-commit")

        rc = _run(pip_cmd)
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


def run_pytest() -> None:
    """Run the test suite using the active Python interpreter.

    This function is exposed as a console script so `uv run pytest` will
    have an executable available after `uv sync` (editable install).
    """
    # Try importing pytest first; if missing, attempt to install dev extras
    try:
        rc = _run([sys.executable, "-m", "pytest"])
        raise SystemExit(rc)
    except Exception:
        print("pytest not found in the active environment.")
        print(
            "Please install the project's development dependencies and hooks before running tests."
        )
        print("Recommended: run the appropriate bootstrap script in the repo root:")
        print("  PowerShell: .\\scripts\\bootstrap-dev.ps1")
        print("  POSIX:     ./scripts/bootstrap-dev.sh")
        raise SystemExit(2)
