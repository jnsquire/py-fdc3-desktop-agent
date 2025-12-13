# Subprocess launcher implementation

import asyncio
import logging
import os
import uuid
from typing import Optional, Dict, Any
from pathlib import Path
from .interfaces import ProcessLauncher, LaunchResult
from ..api import AppIdentifier
from ..storage import LaunchConfig

logger = logging.getLogger(__name__)


class SubprocessLauncher(ProcessLauncher):
    """Launcher that uses subprocess to start app processes"""

    def __init__(self):
        self._running_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._process_events: Dict[str, asyncio.Event] = {}

    async def launch_app(self, app_id: str, launch_config: LaunchConfig,
                        context: Optional[Dict[str, Any]] = None,
                        target: Optional[AppIdentifier] = None) -> LaunchResult:
        """Launch an app process with the given configuration"""
        try:
            # Build command line arguments
            cmd = [launch_config.command] + launch_config.args

            # Prepare environment variables
            env = os.environ.copy()
            env.update(launch_config.env)

            # Add FDC3-specific environment variables
            instance_id = target.instanceId if target and target.instanceId else f"instance_{uuid.uuid4().hex[:8]}"
            instance_uuid = str(uuid.uuid4())

            env.update({
                'FDC3_APP_ID': app_id,
                'FDC3_INSTANCE_ID': instance_id,
                'FDC3_INSTANCE_UUID': instance_uuid,
                'FDC3_DESKTOP_AGENT_URL': 'ws://localhost:8000/ws',  # TODO: Make configurable
            })

            # Add context if provided
            if context:
                env['FDC3_CONTEXT'] = str(context)  # TODO: Proper JSON serialization

            # Determine working directory
            cwd = launch_config.cwd if launch_config.cwd else None
            if cwd and not Path(cwd).is_absolute():
                # Relative to current working directory
                cwd = str(Path.cwd() / cwd)

            logger.info(f"Launching app {app_id} with command: {' '.join(cmd)}")

            # Launch the process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Store the process
            self._running_processes[instance_uuid] = process
            self._process_events[instance_uuid] = asyncio.Event()

            logger.info(f"App {app_id} launched successfully with instance UUID {instance_uuid}")

            return LaunchResult(
                success=True,
                instance_id=instance_id,
                instance_uuid=instance_uuid
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

            del self._running_processes[instance_uuid]
            # Set the exit event
            if instance_uuid in self._process_events:
                self._process_events[instance_uuid].set()
            logger.info(f"Terminated app instance {instance_uuid}")
            return True

        except Exception as e:
            logger.error(f"Failed to terminate app instance {instance_uuid}: {e}")
            return False

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
            
    async def wait_for_app_exit(self, instance_uuid: str, timeout: Optional[float] = None) -> bool:
        """Wait for an app instance to exit. Returns True if it exited, False if timeout."""
        if instance_uuid not in self._process_events:
            return True  # Already exited or never existed

        try:
            await asyncio.wait_for(self._process_events[instance_uuid].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False