# Subprocess launcher implementation

import asyncio
import json
import logging
import os
import uuid
from typing import Optional, Dict
from fdc3.models.dacp.dacp import Fdc3Context
from pathlib import Path
from .interfaces import ProcessLauncher, LaunchResult
from ..api import AppIdentifier
from ..storage import LaunchConfig

logger = logging.getLogger(__name__)


class SubprocessLauncher(ProcessLauncher):
    """Launcher that uses subprocess to start app processes"""

    def __init__(self, agent_url: str = "ws://localhost:8000/ws"):
        self._running_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._process_events: Dict[str, asyncio.Event] = {}
        self._agent_url = agent_url

    async def launch_app(
        self,
        app_id: str,
        launch_config: LaunchConfig,
        context: Optional[Fdc3Context] = None,
        target: Optional[AppIdentifier] = None,
    ) -> LaunchResult:
        """Launch an app process with the given configuration"""
        try:
            # Build command line arguments
            cmd = [launch_config.command] + launch_config.args

            # Prepare environment variables
            env = os.environ.copy()
            env.update(launch_config.env)

            # Add FDC3-specific environment variables
            instance_id = (
                target.instanceId
                if target and target.instanceId
                else f"instance_{uuid.uuid4().hex[:8]}"
            )
            instance_uuid = str(uuid.uuid4())

            env.update(
                {
                    "FDC3_APP_ID": app_id,
                    "FDC3_INSTANCE_ID": instance_id,
                    "FDC3_INSTANCE_UUID": instance_uuid,
                    "FDC3_DESKTOP_AGENT_URL": self._agent_url,
                }
            )

            # Add context if provided
            if context:
                env["FDC3_CONTEXT"] = json.dumps(context)

            # Determine working directory
            cwd = launch_config.cwd if launch_config.cwd else None
            if cwd and not Path(cwd).is_absolute():
                # Relative to current working directory
                cwd = str(Path.cwd() / cwd)

            logger.info(f"Launching app {app_id} with command: {' '.join(cmd)}")

            # Launch the process
            # By default do not capture stdout/stderr to avoid creating pipe transports
            process = await asyncio.create_subprocess_exec(
                *cmd, env=env, cwd=cwd, stdout=None, stderr=None
            )

            # Store the process
            self._running_processes[instance_uuid] = process
            self._process_events[instance_uuid] = asyncio.Event()

            # Start a background reaper to clean up transports when the process exits
            from ..tools import create_task_safe  # local import to avoid cycles

            create_task_safe(self._reap_process(instance_uuid, process))

            logger.info(
                f"App {app_id} launched successfully with instance UUID {instance_uuid}"
            )

            return LaunchResult(
                success=True, instance_id=instance_id, instance_uuid=instance_uuid
            )

        except Exception as e:
            logger.error(f"Failed to launch app {app_id}: {e}")
            return LaunchResult(success=False, error=str(e))

    async def terminate_app(self, instance_uuid: str) -> bool:
        """Terminate a running app instance"""
        if instance_uuid not in self._running_processes:
            logger.warning(f"No running process found for instance {instance_uuid}")
            return False

        process = self._running_processes[instance_uuid]
        try:
            process.terminate()
            # Wait for up to 5 seconds for graceful termination
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                # Force kill if it doesn't terminate gracefully
                process.kill()
                await process.wait()
            # Attempt to close underlying transports to avoid hanging proactor pipes
            try:
                tr = getattr(process, "_transport", None)
                if tr is not None:
                    try:
                        tr.close()
                    except Exception:
                        pass
            except Exception:
                pass

            # Clear stored refs
            try:
                if instance_uuid in self._process_events:
                    self._process_events[instance_uuid].set()
            except Exception:
                pass

            try:
                del self._running_processes[instance_uuid]
            except Exception:
                pass
            logger.info(f"Terminated app instance {instance_uuid}")
            return True

        except Exception as e:
            logger.error(f"Failed to terminate app instance {instance_uuid}: {e}")
            return False

    async def _reap_process(
        self, instance_uuid: str, process: asyncio.subprocess.Process
    ) -> None:
        """Background task: wait for process exit and ensure transports are closed."""
        try:
            await process.wait()
        except Exception:
            pass

        # Attempt to close underlying transports to avoid hanging proactor pipes
        try:
            tr = getattr(process, "_transport", None)
            if tr is not None:
                try:
                    tr.close()
                except Exception:
                    pass
        except Exception:
            pass

        # Also try to close stdout/stderr stream transports if present
        for stream_name in ("stdout", "stderr"):
            try:
                stream = getattr(process, stream_name, None)
                if stream is not None:
                    tr = getattr(stream, "_transport", None)
                    if tr is not None:
                        try:
                            tr.close()
                        except Exception:
                            pass
            except Exception:
                pass

        # Signal any waiters and remove references
        try:
            if instance_uuid in self._process_events:
                self._process_events[instance_uuid].set()
        except Exception:
            pass

        try:
            if instance_uuid in self._running_processes:
                del self._running_processes[instance_uuid]
        except Exception:
            pass
        # Yield control once to let the event loop finalize transports on Windows
        # without introducing a fixed sleep.
        try:
            from ..tools import yield_once  # local import to avoid cycles

            await yield_once()
        except Exception:
            pass

    async def is_app_running(self, instance_uuid: str) -> bool:
        """Check if an app instance is still running"""
        if instance_uuid not in self._running_processes:
            return False

        process = self._running_processes[instance_uuid]
        # For asyncio subprocess, returncode is updated automatically.
        # We don't need to poll, just check if it's still None.

        # If process has exited, set the event
        if process.returncode is not None and instance_uuid in self._process_events:
            self._process_events[instance_uuid].set()
            # Remove from running processes while we're here
            del self._running_processes[instance_uuid]

        return process.returncode is None

    async def wait_for_app_exit(
        self, instance_uuid: str, timeout: Optional[float] = None
    ) -> bool:
        """Wait for an app instance to exit. Returns True if it exited, False if timeout."""
        if instance_uuid not in self._process_events:
            return True  # Already exited or never existed

        try:
            await asyncio.wait_for(
                self._process_events[instance_uuid].wait(), timeout=timeout
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        """Stop all running subprocesses and close their transports/pipes."""
        uuids = list(self._running_processes.keys())
        for instance_uuid in uuids:
            proc = self._running_processes.get(instance_uuid)
            if not proc:
                continue
            try:
                if proc.returncode is None:
                    try:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                            await proc.wait()
                        except Exception:
                            pass
            except Exception:
                pass

            # Attempt to close underlying transports to avoid hanging proactor pipes
            try:
                tr = getattr(proc, "_transport", None)
                if tr is not None:
                    try:
                        tr.close()
                    except Exception:
                        pass
            except Exception:
                pass

            # Also try to close stdout/stderr stream transports if present
            for stream_name in ("stdout", "stderr"):
                try:
                    stream = getattr(proc, stream_name, None)
                    if stream is not None:
                        tr = getattr(stream, "_transport", None)
                        if tr is not None:
                            try:
                                tr.close()
                            except Exception:
                                pass
                except Exception:
                    pass

            # Clear stored refs
            try:
                if instance_uuid in self._process_events:
                    self._process_events[instance_uuid].set()
            except Exception:
                pass

            try:
                del self._running_processes[instance_uuid]
            except Exception:
                pass

        # Ensure events dict is cleared
        self._process_events.clear()
