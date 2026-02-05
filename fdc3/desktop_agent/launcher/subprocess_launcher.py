# Subprocess launcher implementation

import asyncio
import json
import logging
import os
import uuid
from typing import Optional, Dict
from fdc3.models.dacp.dacp import Fdc3Context
from fdc3.models.identifiers import AppIdentifier
from fdc3.desktop_agent.launcher.interfaces import ProcessLauncher, LaunchResult
from fdc3.desktop_agent.storage import LaunchConfig
from fdc3.desktop_agent.tools import create_task_safe, yield_once
from pathlib import Path

logger = logging.getLogger(__name__)


class SubprocessLauncher(ProcessLauncher):
    """Launcher that uses subprocess to start app processes"""

    def __init__(self, agent_url: str = "ws://localhost:8000/ws"):
        self._running_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._process_events: Dict[str, asyncio.Event] = {}
        self._agent_url = agent_url

    def _normalize_cwd(self, cwd: Optional[str]) -> Optional[str]:
        if not cwd:
            return None
        path = Path(cwd)
        if path.is_absolute():
            return str(path)
        return str(Path.cwd() / path)

    def _set_process_event(self, instance_uuid: str) -> None:
        event = self._process_events.get(instance_uuid)
        if event is not None:
            event.set()

    def _remove_process(self, instance_uuid: str) -> None:
        self._running_processes.pop(instance_uuid, None)

    def _close_transports(self, process: asyncio.subprocess.Process) -> None:
        """Best-effort close of underlying transports to avoid hanging proactor pipes."""
        try:
            tr = getattr(process, "_transport", None)
            if tr is not None:
                tr.close()
        except Exception:
            pass

        for stream_name in ("stdout", "stderr"):
            try:
                stream = getattr(process, stream_name, None)
                if stream is not None:
                    tr = getattr(stream, "_transport", None)
                    if tr is not None:
                        tr.close()
            except Exception:
                pass

    async def launch_app(
        self,
        app_id: str,
        launch_config: LaunchConfig,
        context: Optional[Fdc3Context] = None,
        target: Optional[AppIdentifier] = None,
    ) -> LaunchResult:
        """Launch an app process with the given configuration"""
        try:
            if not launch_config.command:
                return LaunchResult(success=False, error="Launch command is required")

            # Build command line arguments
            cmd = [launch_config.command] + (launch_config.args or [])

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
                try:
                    env["FDC3_CONTEXT"] = json.dumps(context)
                except (TypeError, ValueError) as exc:
                    return LaunchResult(
                        success=False, error=f"Failed to serialize context: {exc}"
                    )

            # Determine working directory
            cwd = self._normalize_cwd(launch_config.cwd)

            logger.info("Launching app %s with command: %s", app_id, " ".join(cmd))

            # Launch the process
            # By default do not capture stdout/stderr to avoid creating pipe transports
            process = await asyncio.create_subprocess_exec(
                *cmd, env=env, cwd=cwd, stdout=None, stderr=None
            )

            # Store the process
            self._running_processes[instance_uuid] = process
            self._process_events[instance_uuid] = asyncio.Event()

            # Start a background reaper to clean up transports when the process exits
            create_task_safe(self._reap_process(instance_uuid, process))

            logger.info(
                "App %s launched successfully with instance UUID %s",
                app_id,
                instance_uuid,
            )

            return LaunchResult(
                success=True, instance_id=instance_id, instance_uuid=instance_uuid
            )

        except Exception as e:
            logger.exception("Failed to launch app %s", app_id)
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
            self._close_transports(process)

            self._set_process_event(instance_uuid)
            self._remove_process(instance_uuid)
            logger.info("Terminated app instance %s", instance_uuid)
            return True

        except Exception:
            logger.exception("Failed to terminate app instance %s", instance_uuid)
            return False

    async def _reap_process(
        self, instance_uuid: str, process: asyncio.subprocess.Process
    ) -> None:
        """Background task: wait for process exit and ensure transports are closed."""
        try:
            await process.wait()
        except Exception:
            pass

        self._close_transports(process)

        # Signal any waiters and remove references
        self._set_process_event(instance_uuid)
        self._remove_process(instance_uuid)
        # Yield control once to let the event loop finalize transports on Windows
        # without introducing a fixed sleep.
        try:
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
            self._set_process_event(instance_uuid)
            self._remove_process(instance_uuid)

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

            self._close_transports(proc)

            self._set_process_event(instance_uuid)
            self._remove_process(instance_uuid)

        # Ensure events dict is cleared
        self._process_events.clear()
