---
description: Knows the project development rules
tools:
  [
    "execute/runTests",
    "read",
    "edit",
    "search",
    "web",
    "agent",
    "ms-python.python/installPythonPackage",
    "todo",
  ]
---

# Developer Agent

As a developer on this project, you should follow the following guidelines.

- Prefer `uv` commands for running tasks.
- Use `uv run ruff` for linting and formatting before committing code.

## Bootstrap scripts

- Windows (PowerShell): `scripts/bootstrap-dev.ps1`
- macOS/Linux: `scripts/bootstrap-dev.sh`

These scripts install dev deps, set up pre-commit hooks, and run pre-commit once across the repo.
