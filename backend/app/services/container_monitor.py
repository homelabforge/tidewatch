"""Container monitoring service for detecting crashes and exit codes."""

import logging
import os
from typing import Dict, Optional, Tuple

import docker
from docker.errors import DockerException, NotFound

from app.services.compose_parser import validate_container_name

logger = logging.getLogger(__name__)


class ContainerMonitorService:
    """Monitor container health, exit codes, and failure states."""

    def __init__(self) -> None:
        """Initialize with Docker client."""
        # Use DOCKER_HOST if set, otherwise use default Unix socket
        docker_host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
        self.client = docker.DockerClient(base_url=docker_host)

    async def get_container_state(self, container_name: str) -> Optional[Dict]:
        """Get full container state including exit codes using Docker SDK.

        Args:
            container_name: Name of the container

        Returns:
            Dictionary with container state or None if error
        """
        # Validate container name to prevent command injection
        if not validate_container_name(container_name):
            logger.warning(
                f"Invalid container name '{container_name}', rejecting for security"
            )
            return {"error": "Invalid container name", "running": False}

        try:
            container = self.client.containers.get(container_name)
            container.reload()  # Refresh container data

            state = container.attrs.get("State", {})

            return {
                "status": state.get("Status"),  # running, exited, restarting, paused
                "running": state.get("Running", False),
                "paused": state.get("Paused", False),
                "restarting": state.get("Restarting", False),
                "oom_killed": state.get("OOMKilled", False),
                "dead": state.get("Dead", False),
                "exit_code": state.get("ExitCode"),
                "error": state.get("Error", ""),
                "started_at": state.get("StartedAt"),
                "finished_at": state.get("FinishedAt"),
                "restart_count": state.get("RestartCount", 0),
                "health": state.get("Health", {}),
            }
        except NotFound:
            return {"error": "Container not found", "running": False}
        except DockerException as e:
            logger.error(f"Docker error getting state for {container_name}: {e}")
            return {"error": str(e), "running": False}
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid container data for {container_name}: {e}")
            return {"error": str(e), "running": False}

    @staticmethod
    async def should_retry_restart(
        exit_code: Optional[int], oom_killed: bool
    ) -> Tuple[bool, str]:
        """Determine if container should be restarted based on exit code.

        Exit code semantics:
        - 0: Clean shutdown (don't retry)
        - 1: Application error (retry)
        - 125: Docker daemon error (maybe retry with limit)
        - 126: Command cannot be invoked (don't retry - config issue)
        - 127: Command not found (don't retry - config issue)
        - 128+n: Killed by signal n (retry)
        - 137: SIGKILL, often OOM (retry but warn)
        - 143: SIGTERM (retry)

        Args:
            exit_code: Container exit code (None if container is running)
            oom_killed: Whether container was OOM killed

        Returns:
            (should_retry, reason_code)
        """
        # Container still running or no exit code - don't retry
        if exit_code is None:
            return False, "no_exit_code"

        # Clean shutdown - don't retry
        if exit_code == 0:
            return False, "clean_shutdown"

        # Configuration errors - don't retry
        if exit_code in [126, 127]:
            return False, f"config_error_{exit_code}"

        # OOM killed - retry but log warning
        if oom_killed:
            logger.warning(
                "Container was OOM killed - consider increasing memory limits"
            )
            return True, "oom_killed"

        # Application error - retry
        if exit_code == 1:
            return True, "application_error"

        # Docker daemon error - maybe retry (use with caution)
        if exit_code == 125:
            return True, "docker_daemon_error"

        # Signal killed - retry
        if exit_code >= 128:
            signal_num = exit_code - 128
            signal_name = {
                9: "SIGKILL",
                15: "SIGTERM",
                2: "SIGINT",
                3: "SIGQUIT",
                6: "SIGABRT",
            }.get(signal_num, f"SIG{signal_num}")

            return True, f"signal_killed_{signal_name}"

        # Default: retry for any non-zero exit code
        return True, f"exit_code_{exit_code}"

    async def get_container_exit_info(self, container_name: str) -> Optional[Dict]:
        """Get detailed exit information for a stopped container.

        Args:
            container_name: Name of the container

        Returns:
            Exit information dictionary or None if error
        """
        state = await self.get_container_state(container_name)

        if not state or state.get("running"):
            return None

        return {
            "exit_code": state.get("exit_code"),
            "oom_killed": state.get("oom_killed", False),
            "error": state.get("error", ""),
            "finished_at": state.get("finished_at"),
            "restart_count": state.get("restart_count", 0),
            "status": state.get("status"),
        }

    async def check_health_status(self, container_name: str) -> Dict:
        """Check container health status using Docker SDK.

        Args:
            container_name: Name of the container

        Returns:
            Health status dictionary
        """
        state = await self.get_container_state(container_name)

        if not state or not state.get("running"):
            return {
                "healthy": False,
                "status": "not_running",
                "error": state.get("error") if state else "Container not found",
            }

        health = state.get("health", {})
        health_status = health.get("Status")  # starting, healthy, unhealthy

        if not health_status:
            # No health check configured, assume healthy if running
            return {
                "healthy": state.get("running", False),
                "status": "running",
                "health_check_configured": False,
            }

        return {
            "healthy": health_status == "healthy",
            "status": health_status,
            "health_check_configured": True,
            "failing_streak": health.get("FailingStreak", 0),
            "log": health.get("Log", [])[-1] if health.get("Log") else None,
        }

    @staticmethod
    def categorize_failure(
        exit_code: Optional[int], oom_killed: bool, error: str
    ) -> str:
        """Categorize the type of container failure.

        Args:
            exit_code: Container exit code (None if container is running)
            oom_killed: Whether OOM killed
            error: Error message from docker

        Returns:
            Failure category string
        """
        if oom_killed:
            return "oom_killed"

        if exit_code is None:
            return "no_exit_code"

        if exit_code == 0:
            return "clean_shutdown"

        if exit_code in [126, 127]:
            return "configuration_error"

        if exit_code == 1:
            return "application_error"

        if exit_code == 125:
            return "docker_error"

        if exit_code == 137:
            return "sigkill"

        if exit_code == 143:
            return "sigterm"

        if exit_code >= 128:
            return f"signal_{exit_code - 128}"

        if error:
            return "runtime_error"

        return f"unknown_exit_{exit_code}"


# Singleton instance
container_monitor = ContainerMonitorService()
