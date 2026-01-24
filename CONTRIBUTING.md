# Contributing & Distributed Adapter Setup

Thank you for contributing to the FDC3 Desktop Agent. This document covers contribution basics and optional distributed adapter setup (etcd / Consul) used to relay channel events across multiple agent workers.

## Running tests locally

- Install dev dependencies (editable install recommended):

```bash
python -m pip install -e '.[dev]'
```

- Run the test suite:

```bash
python -m pytest
```

## Code style (required)

After each major change, run the following commands to fix lint issues and format files:

```bash
uv run ruff check --fix
uv run ruff format
```

## Developer setup

This repository includes helper scripts to bootstrap a developer environment and install git hooks.

- Windows (PowerShell): `scripts/bootstrap-dev.ps1`
- POSIX (macOS / Linux): `scripts/bootstrap-dev.sh`

`install-git-hooks` is provided as a console script entry (installed when you run an editable install). After installing dev deps you can run:

```powershell
# Windows
install-git-hooks

# or explicitly via the venv
.venv\Scripts\install-git-hooks
```

Each script will (when run from the repository root):

- install or upgrade `pip` in the `.venv` virtualenv
- install the project's development extras (`.[dev]`) into the `.venv`
- install `pre-commit` hooks into `.git/hooks`
- run `pre-commit` once across the repository to auto-fix style issues

Examples:

PowerShell

```powershell
./scripts/bootstrap-dev.ps1
```

POSIX

```bash
./scripts/bootstrap-dev.sh
```

If you prefer manual steps, the equivalent commands are:

```bash
# install dev deps
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e '.[dev]'

# install pre-commit hooks
./.venv/bin/pre-commit install --install-hooks

# run pre-commit once
./.venv/bin/pre-commit run --all-files
```

CI should install the same extras so tests can be executed (see CI note below).

## Distributed adapters (optional)

The project supports optional distributed adapters to relay `channel_events` across workers. These adapters are optional and require extra dependencies:

- `etcd` adapter: requires `etcd3` or an HTTP gateway client (`etcd3gw`) and a running etcd cluster.
- `consul` adapter: requires `aiohttp` and a running Consul agent.

To enable an adapter set the environment variable `FDC3_DISTRIBUTED_ADAPTER` to one of:

- `etcd` — enable etcd adapter
- `consul` — enable Consul adapter
- unset or any other value — no distributed adapter (local-only)

Install adapter dependencies via pip extras:

```bash
# etcd only
pip install .[etcd]

# consul only
pip install .[consul]

# both
pip install .[distributed]
```

Adapters in this repository are prototypes and intended as examples. They operate best-effort — adapter failures will not stop local event delivery.

### Quick Docker examples

Run a single-node etcd for local testing:

```bash
docker run -d --name etcd --publish 2379:2379 quay.io/coreos/etcd:v3.5.0 /usr/local/bin/etcd \
  --advertise-client-urls http://0.0.0.0:2379 --listen-client-urls http://0.0.0.0:2379
```

Run Consul in dev mode for local testing:

```bash
docker run -d --name=consul -p 8500:8500 consul:latest agent -dev -client=0.0.0.0
```

## CI configuration notes

- Ensure CI installs dev extras so the tests and test clients (e.g. `httpx`) are available. Example step:

```yaml
- name: Install deps
  run: python -m pip install -e '.[dev]'
```

- If you do not want to run distributed adapters in CI, ensure `FDC3_DISTRIBUTED_ADAPTER` is unset or set to `noop`.

## Reporting issues & PR guidelines

- Open issues for bugs or design discussions.
- Keep changes small and focused; update tests when adding behavior.
- Run `ruff` and `black` locally to keep style consistent.

Thanks for contributing!
