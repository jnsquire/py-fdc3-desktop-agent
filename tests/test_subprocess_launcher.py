import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, cast

import pytest

from fdc3.desktop_agent.launcher.subprocess_launcher import SubprocessLauncher
from fdc3.desktop_agent.storage.interfaces import LaunchConfig
from fdc3.desktop_agent.api import AppIdentifier


class _FakeTransport:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeStream:
    def __init__(self):
        self._transport = _FakeTransport()


class _FakeProcess:
    def __init__(self, *, returncode: Optional[int] = None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self._transport = _FakeTransport()
        # Optional stream attributes (used defensively by stop/_reap_process)
        self.stdout = None
        self.stderr = None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    async def wait(self):
        # Simulate process exit
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.mark.asyncio
async def test_launch_app_injects_env_and_resolves_relative_cwd(monkeypatch):
    captured: Dict[str, Any] = {}

    async def fake_create_subprocess_exec(
        *cmd, env=None, cwd=None, stdout=None, stderr=None
    ):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(env or {})
        captured["cwd"] = cwd
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        return _FakeProcess()

    # Avoid background task side effects (and close the coroutine to prevent warnings).
    def discard_task(coro):
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return None

    monkeypatch.setattr(
        "fdc3.desktop_agent.tools.create_task_safe",
        discard_task,
        raising=True,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: Path("C:/base")))

    launcher = SubprocessLauncher(agent_url="ws://example/ws")
    cfg = LaunchConfig(
        app_id="app-1",
        command="python",
        args=["-c", "print('hi')"],
        env={"FOO": "BAR"},
        cwd="relative/dir",
        timeout=30,
    )

    result = await launcher.launch_app(app_id="app-1", launch_config=cfg)
    assert result.success is True

    assert captured["cmd"] == ["python", "-c", "print('hi')"]
    assert captured["cwd"].replace("\\", "/").endswith("C:/base/relative/dir")

    env = captured["env"]
    assert env["FOO"] == "BAR"
    assert env["FDC3_APP_ID"] == "app-1"
    assert env["FDC3_DESKTOP_AGENT_URL"] == "ws://example/ws"
    assert env["FDC3_INSTANCE_ID"].startswith("instance_")
    assert isinstance(env["FDC3_INSTANCE_UUID"], str) and env["FDC3_INSTANCE_UUID"]


@pytest.mark.asyncio
async def test_launch_app_uses_target_instance_id(monkeypatch):
    captured: Dict[str, Any] = {}

    async def fake_create_subprocess_exec(
        *cmd, env=None, cwd=None, stdout=None, stderr=None
    ):
        captured["env"] = dict(env or {})
        return _FakeProcess()

    def discard_task(coro):
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return None

    monkeypatch.setattr(
        "fdc3.desktop_agent.tools.create_task_safe",
        discard_task,
        raising=True,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    launcher = SubprocessLauncher(agent_url="ws://example/ws")
    cfg = LaunchConfig(
        app_id="app-1",
        command="python",
        args=[],
        env={},
        cwd="",
        timeout=30,
    )

    target = AppIdentifier(appId="app-1", instanceId="fixed-instance")
    result = await launcher.launch_app(app_id="app-1", launch_config=cfg, target=target)
    assert result.success is True
    assert captured["env"]["FDC3_INSTANCE_ID"] == "fixed-instance"


@pytest.mark.asyncio
async def test_is_app_running_removes_exited_process_and_sets_event():
    launcher = SubprocessLauncher()
    proc = _FakeProcess(returncode=0)
    cast(dict[str, Any], launcher._running_processes)["u1"] = proc
    launcher._process_events["u1"] = asyncio.Event()

    running = await launcher.is_app_running("u1")
    assert running is False
    assert "u1" not in launcher._running_processes
    assert launcher._process_events["u1"].is_set() is True


@pytest.mark.asyncio
async def test_wait_for_app_exit_returns_true_when_unknown():
    launcher = SubprocessLauncher()
    assert await launcher.wait_for_app_exit("missing", timeout=0.01) is True


@pytest.mark.asyncio
async def test_terminate_app_graceful_removes_process_and_sets_event():
    launcher = SubprocessLauncher()
    proc = _FakeProcess(returncode=None)
    cast(dict[str, Any], launcher._running_processes)["u1"] = proc
    launcher._process_events["u1"] = asyncio.Event()

    ok = await launcher.terminate_app("u1")
    assert ok is True
    assert proc.terminated is True
    assert proc.killed is False
    assert "u1" not in launcher._running_processes
    assert launcher._process_events["u1"].is_set() is True


@pytest.mark.asyncio
async def test_terminate_app_timeout_kills(monkeypatch):
    launcher = SubprocessLauncher()

    class SlowProcess(_FakeProcess):
        def __init__(self):
            super().__init__(returncode=None)
            self._exit_event = asyncio.Event()

        def kill(self):
            super().kill()
            # Unblock wait() after kill() so terminate_app can't hang.
            self.returncode = 1
            self._exit_event.set()

        async def wait(self):
            await self._exit_event.wait()
            return self.returncode if self.returncode is not None else 1

    proc = SlowProcess()
    cast(dict[str, Any], launcher._running_processes)["u1"] = proc
    launcher._process_events["u1"] = asyncio.Event()

    async def fake_wait_for(awaitable, timeout=None):
        # Only force timeout for the process wait; close the coroutine to avoid warnings.
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    ok = await launcher.terminate_app("u1")
    assert ok is True
    assert proc.terminated is True
    assert proc.killed is True


@pytest.mark.asyncio
async def test_stop_terminates_all_processes_and_clears_events(monkeypatch):
    launcher = SubprocessLauncher()

    p1 = _FakeProcess(returncode=None)
    p2 = _FakeProcess(returncode=0)
    # Give p1 stream transports to exercise defensive close logic
    p1.stdout = _FakeStream()
    p1.stderr = _FakeStream()

    cast(dict[str, Any], launcher._running_processes)["u1"] = p1
    cast(dict[str, Any], launcher._running_processes)["u2"] = p2
    launcher._process_events["u1"] = asyncio.Event()
    launcher._process_events["u2"] = asyncio.Event()

    await launcher.stop()

    assert launcher._process_events == {}
    assert launcher._running_processes == {}
    assert p1._transport.closed is True
    assert p1.stdout._transport.closed is True
    assert p1.stderr._transport.closed is True
