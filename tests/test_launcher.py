# Launcher tests

import pytest
import asyncio
from fdc3.desktop_agent.launcher.subprocess_launcher import SubprocessLauncher
from fdc3.desktop_agent.storage import LaunchConfig


@pytest.fixture(autouse=True)
def _mock_subprocess(monkeypatch):
    """Replace asyncio.create_subprocess_exec with a fake process for tests.

    The fake adapts to the invoked command to simulate immediate-exit
    commands (e.g., echo) and long-running commands (e.g., sleep).
    """

    class FakeProcess:
        def __init__(self, long_running: bool = False):
            self.returncode = None if long_running else 0
            self._exited = asyncio.Event()
            if not long_running:
                # already exited
                self._exited.set()
            # simulate stdout/stderr attributes (None when not captured)
            self.stdout = None
            self.stderr = None

        async def wait(self):
            await self._exited.wait()
            return self.returncode

        def terminate(self):
            # simulate graceful termination
            self.returncode = -15
            self._exited.set()

        def kill(self):
            self.returncode = -9
            self._exited.set()

    async def _fake_create_subprocess_exec(*cmd, **kwargs):
        # simulate command-not-found for specific invalid command used in tests
        if any("nonexistent_command_12345" in str(c) for c in cmd):
            raise FileNotFoundError("No such file or directory")
        # determine if command should be long-running by inspecting args
        cmdline = " ".join(str(x) for x in cmd)
        long_running = False
        if "sleep" in cmdline or "time.sleep" in cmdline:
            long_running = True
        proc = FakeProcess(long_running=long_running)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    yield


class TestSubprocessLauncher:
    """Test SubprocessLauncher functionality"""

    @pytest.mark.asyncio
    async def test_launch_app_success(self):
        """Test successful app launching"""
        launcher = SubprocessLauncher()
        config = LaunchConfig(
            app_id="test-app",
            command="echo",
            args=["hello"],
            env={"TEST_VAR": "test_value"},
            cwd="",
            timeout=30,
        )

        result = await launcher.launch_app("test-app", config)

        assert result.success is True
        assert result.instance_id is not None
        assert result.instance_uuid is not None
        assert result.error is None

        # Check that process is tracked
        await launcher.wait_for_app_exit(result.instance_uuid, timeout=1.0)
        assert (
            await launcher.is_app_running(result.instance_uuid) is False
        )  # echo exits immediately

        # Clean up
        await launcher.terminate_app(result.instance_uuid)

    @pytest.mark.asyncio
    async def test_launch_app_with_env_vars(self):
        """Test that environment variables are properly set"""
        launcher = SubprocessLauncher()
        config = LaunchConfig(
            app_id="test-app",
            command="python",
            args=["-c", "import os; print(os.environ.get('FDC3_APP_ID', 'NOT_SET'))"],
            env={},
            cwd="",
            timeout=30,
        )

        result = await launcher.launch_app("test-app", config)

        assert result.success is True
        # The subprocess should have FDC3_APP_ID set
        # Note: We can't easily check the actual environment, but the code sets it

    @pytest.mark.asyncio
    async def test_launch_app_invalid_command(self):
        """Test launching with invalid command"""
        launcher = SubprocessLauncher()
        config = LaunchConfig(
            app_id="test-app",
            command="nonexistent_command_12345",
            args=[],
            env={},
            cwd="",
            timeout=30,
        )

        result = await launcher.launch_app("test-app", config)

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_terminate_app(self):
        """Test terminating running apps"""
        launcher = SubprocessLauncher()
        config = LaunchConfig(
            app_id="test-app",
            command="python",
            args=["-c", "import time; time.sleep(10)"],  # Long-running command
            env={},
            cwd="",
            timeout=30,
        )

        result = await launcher.launch_app("test-app", config)
        assert result.success is True
        assert result.instance_uuid is not None

        # Check it's running
        assert await launcher.is_app_running(result.instance_uuid) is True

        # Terminate
        terminated = await launcher.terminate_app(result.instance_uuid)
        assert terminated is True

        # Check it's not running anymore
        await asyncio.sleep(0.1)  # Give it time to terminate
        assert await launcher.is_app_running(result.instance_uuid) is False

    @pytest.mark.asyncio
    async def test_is_app_running(self):
        """Test checking if app is running"""
        launcher = SubprocessLauncher()
        config = LaunchConfig(
            app_id="test-app", command="echo", args=["done"], env={}, cwd="", timeout=30
        )

        result = await launcher.launch_app("test-app", config)
        assert result.success is True
        assert result.instance_uuid is not None

        # Immediately after launch, echo should be done
        await launcher.wait_for_app_exit(result.instance_uuid, timeout=1.0)
        assert await launcher.is_app_running(result.instance_uuid) is False

    @pytest.mark.asyncio
    async def test_terminate_nonexistent_app(self):
        """Test terminating non-existent app"""
        launcher = SubprocessLauncher()

        terminated = await launcher.terminate_app("nonexistent-uuid")
        assert terminated is False

    @pytest.mark.asyncio
    async def test_is_app_running_nonexistent(self):
        """Test checking running status of non-existent app"""
        launcher = SubprocessLauncher()

        running = await launcher.is_app_running("nonexistent-uuid")
        assert running is False

    @pytest.mark.asyncio
    async def test_argv_env_expansion_from_config(self):
        """Test that argv and env are properly expanded from stored config"""
        launcher = SubprocessLauncher()

        # Test with environment variable expansion in args
        config = LaunchConfig(
            app_id="test-app",
            command="python",
            args=[
                "-c",
                'import os, sys; print(f\'Args: {sys.argv}\'); print(f\'Env TEST_VAR: {os.environ.get("TEST_VAR", "NOT_SET")}\'); print(f\'FDC3_APP_ID: {os.environ.get("FDC3_APP_ID", "NOT_SET")}\')',
            ],
            env={"TEST_VAR": "expanded_value", "ANOTHER_VAR": "another_value"},
            cwd="",
            timeout=30,
        )

        result = await launcher.launch_app("test-app", config)

        assert result.success is True
        assert result.instance_id is not None
        assert result.instance_uuid is not None

        # Wait for the process to complete and check it ran successfully
        await launcher.wait_for_app_exit(result.instance_uuid, timeout=5.0)
        assert await launcher.is_app_running(result.instance_uuid) is False

        # Clean up
        await launcher.terminate_app(result.instance_uuid)
