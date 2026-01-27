"""Intelligent container restart service with exponential backoff."""

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Container
from app.models.restart_log import ContainerRestartLog
from app.models.restart_state import ContainerRestartState
from app.services.event_bus import event_bus
from app.services.settings_service import SettingsService
from app.services.update_engine import UpdateEngine

logger = logging.getLogger(__name__)


class RestartService:
    """Core service for intelligent container restart with exponential backoff."""

    @staticmethod
    def calculate_exponential_backoff(
        attempt: int,
        base_delay: float = 2.0,
        multiplier: float = 1.0,
        max_delay: float = 300.0,
        jitter: bool = True,
    ) -> float:
        """Calculate exponential backoff delay.

        Formula: min(max_delay, base_delay * multiplier * 2^attempt)

        Args:
            attempt: Retry attempt number (0-indexed)
            base_delay: Base delay in seconds
            multiplier: Multiplier for the exponential function
            max_delay: Maximum delay cap in seconds
            jitter: Add random jitter to prevent thundering herd

        Returns:
            Delay in seconds
        """
        # Calculate exponential delay
        delay = base_delay * multiplier * (2**attempt)

        # Cap at max delay
        delay = min(delay, max_delay)

        # Add jitter (±20% random variation)
        if jitter:
            jitter_amount = delay * 0.2
            delay = delay + random.uniform(-jitter_amount, jitter_amount)
            delay = max(base_delay, delay)  # Never go below base delay

        return delay

    @staticmethod
    def calculate_linear_backoff(
        attempt: int,
        base_delay: float = 5.0,
        increment: float = 10.0,
        max_delay: float = 300.0,
    ) -> float:
        """Calculate linear backoff delay.

        Formula: min(max_delay, base_delay + (increment * attempt))
        """
        delay = base_delay + (increment * attempt)
        return min(delay, max_delay)

    @staticmethod
    def calculate_fixed_backoff(delay: float = 30.0) -> float:
        """Fixed delay between retries."""
        return delay

    @staticmethod
    async def calculate_backoff_delay(
        state: ContainerRestartState, db: AsyncSession
    ) -> float:
        """Calculate backoff delay based on strategy and attempt count.

        Args:
            state: Container restart state
            db: Database session

        Returns:
            Delay in seconds
        """
        attempt = state.consecutive_failures

        if state.backoff_strategy == "exponential":
            return RestartService.calculate_exponential_backoff(
                attempt=attempt,
                base_delay=state.base_delay_seconds,
                max_delay=state.max_delay_seconds,
                jitter=True,
            )
        elif state.backoff_strategy == "linear":
            return RestartService.calculate_linear_backoff(
                attempt=attempt,
                base_delay=state.base_delay_seconds,
                increment=10.0,
                max_delay=state.max_delay_seconds,
            )
        elif state.backoff_strategy == "fixed":
            return RestartService.calculate_fixed_backoff(
                delay=state.base_delay_seconds
            )
        else:
            logger.warning(
                f"Unknown backoff strategy '{state.backoff_strategy}', using exponential"
            )
            return RestartService.calculate_exponential_backoff(
                attempt=attempt,
                base_delay=state.base_delay_seconds,
                max_delay=state.max_delay_seconds,
            )

    @staticmethod
    async def check_circuit_breaker(
        db: AsyncSession, container_id: int
    ) -> tuple[bool, str | None]:
        """Check if circuit breaker is open (preventing restarts).

        Returns:
            (allow_restart, reason_if_blocked)
        """
        result = await db.execute(
            select(ContainerRestartState).where(
                ContainerRestartState.container_id == container_id
            )
        )
        state = result.scalar_one_or_none()

        if not state:
            return True, None

        # Check if manually paused
        if state.paused_until:
            if datetime.now(UTC) < state.paused_until:
                return (
                    False,
                    f"Paused until {state.paused_until.isoformat()} ({state.pause_reason or 'manual'})",
                )
            else:
                # Clear pause
                state.paused_until = None
                state.pause_reason = None
                await db.commit()

        # Check if max retries reached
        if state.max_retries_reached:
            return False, "Maximum retry attempts reached"

        # Check if enabled
        if not state.enabled:
            return False, "Auto-restart disabled for this container"

        # Check global concurrent restart limit
        concurrent_count_result = await db.execute(
            select(func.count(ContainerRestartState.id)).where(
                ContainerRestartState.next_retry_at.isnot(None),
                ContainerRestartState.next_retry_at
                > datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        count = concurrent_count_result.scalar() or 0

        # Get global limit from settings
        concurrent_limit = await SettingsService.get_int(
            db, "restart_concurrent_limit", default=10
        )

        if count >= concurrent_limit:
            return (
                False,
                f"Concurrent restart limit reached ({count}/{concurrent_limit})",
            )

        return True, None

    @staticmethod
    async def check_and_reset_backoff(
        db: AsyncSession, state: ContainerRestartState, container: Container
    ) -> bool:
        """Check if container has been running long enough to reset backoff.

        Returns:
            True if state was reset
        """
        if not state.last_successful_start:
            return False

        # Calculate how long container has been running (uses defensive timezone handling)
        uptime = state.uptime_seconds
        if uptime is None:
            return False

        # If running longer than success window, reset
        if uptime >= state.success_window_seconds:
            logger.info(
                f"Container {container.name} has been running for {uptime:.0f}s, "
                f"resetting restart state"
            )

            state.consecutive_failures = 0
            state.current_backoff_seconds = 0.0
            state.next_retry_at = None
            state.max_retries_reached = False
            state.last_exit_code = None
            state.last_failure_reason = None

            # Keep restart history but truncate to last 100 entries
            history = state.restart_history or []
            if len(history) > 100:
                state.restart_history = history[-100:]

            await db.commit()
            return True

        return False

    @staticmethod
    async def get_or_create_restart_state(
        db: AsyncSession, container: Container
    ) -> ContainerRestartState:
        """Get or create restart state for a container.

        Args:
            db: Database session
            container: Container model

        Returns:
            Container restart state
        """
        result = await db.execute(
            select(ContainerRestartState).where(
                ContainerRestartState.container_id == container.id
            )
        )
        state = result.scalar_one_or_none()

        if not state:
            # Create new state with container's configuration
            state = ContainerRestartState(
                container_id=container.id,
                container_name=container.name,
                enabled=container.auto_restart_enabled,
                max_attempts=container.restart_max_attempts or 10,
                backoff_strategy=container.restart_backoff_strategy or "exponential",
                success_window_seconds=container.restart_success_window or 300,
            )
            db.add(state)
            await db.commit()
            await db.refresh(state)

        return state

    @staticmethod
    async def execute_restart(
        db: AsyncSession,
        container: Container,
        state: ContainerRestartState,
        attempt_number: int,
        trigger_reason: str,
        exit_code: int | None = None,
    ) -> dict:
        """Execute a container restart attempt.

        Args:
            db: Database session
            container: Container to restart
            state: Restart state
            attempt_number: Current attempt number
            trigger_reason: Why restart was triggered
            exit_code: Exit code from container (if applicable)

        Returns:
            Result dictionary with success status
        """
        now = datetime.now(UTC)

        # Create log entry
        log_entry = ContainerRestartLog(
            container_id=container.id,
            container_name=container.name,
            restart_state_id=state.id,
            attempt_number=attempt_number,
            trigger_reason=trigger_reason,
            exit_code=exit_code,
            failure_reason=state.last_failure_reason,
            backoff_strategy=state.backoff_strategy,
            backoff_delay_seconds=state.current_backoff_seconds,
            restart_method="docker_compose",
            health_check_enabled=state.health_check_enabled,
            scheduled_at=state.next_retry_at or now,
            executed_at=now,
            success=False,  # Will update later
        )
        db.add(log_entry)
        await db.commit()

        # Publish event
        await event_bus.publish(
            {
                "type": "restart-attempt",
                "container_id": container.id,
                "container_name": container.name,
                "attempt": attempt_number,
                "status": "in_progress",
                "trigger_reason": trigger_reason,
                "backoff_delay": state.current_backoff_seconds,
            }
        )

        logger.info(
            f"Attempting restart of {container.name} "
            f"(attempt {attempt_number}/{state.max_attempts})"
        )

        try:
            # Execute docker compose restart
            restart_result = await RestartService._execute_docker_compose_restart(
                container, db
            )

            log_entry.docker_command = restart_result.get("command")
            log_entry.duration_seconds = restart_result.get("duration")

            if not restart_result["success"]:
                log_entry.success = False
                log_entry.error_message = restart_result.get("error", "Unknown error")
                log_entry.completed_at = datetime.now(UTC)
                await db.commit()

                logger.error(
                    f"Failed to restart {container.name}: {restart_result.get('error')}"
                )
                return {"success": False, "error": restart_result.get("error")}

            # Wait a moment for container to start (configurable delay)
            from app.services.settings_service import SettingsService

            startup_delay = await SettingsService.get_int(
                db, "container_startup_delay", default=2
            )
            await asyncio.sleep(startup_delay)

            # Validate health check if enabled
            health_result = {"healthy": True, "method": "none"}
            if state.health_check_enabled and container.health_check_url:
                health_result = await RestartService._validate_health_check(
                    container, state.health_check_timeout, db
                )

                log_entry.health_check_passed = health_result["healthy"]
                log_entry.health_check_duration = health_result.get("duration")
                log_entry.health_check_method = health_result.get("method")
                log_entry.health_check_error = health_result.get("error")

                if not health_result["healthy"]:
                    log_entry.success = False
                    log_entry.error_message = (
                        f"Health check failed: {health_result.get('error')}"
                    )
                    log_entry.completed_at = datetime.now(UTC)
                    await db.commit()

                    logger.warning(
                        f"Health check failed for {container.name} after restart"
                    )
                    return {
                        "success": False,
                        "error": "Health check failed",
                        "health": health_result,
                    }

            # Success!
            log_entry.success = True
            log_entry.final_container_status = "running"
            log_entry.completed_at = datetime.now(UTC)

            # Update state
            state.last_successful_start = now
            state.consecutive_failures = 0  # Reset on success
            state.current_backoff_seconds = 0.0
            state.next_retry_at = None
            state.last_exit_code = None
            state.last_failure_reason = None
            state.total_restarts += 1
            state.add_restart_to_history(now)

            await db.commit()

            logger.info(f"Successfully restarted {container.name}")

            # Publish success event
            await event_bus.publish(
                {
                    "type": "restart-complete",
                    "container_id": container.id,
                    "container_name": container.name,
                    "attempt": attempt_number,
                    "status": "success",
                    "health_check": health_result,
                }
            )

            # Send notification if enabled
            notify_on_success = await SettingsService.get_bool(
                db, "restart_notify_on_success", default=False
            )
            if notify_on_success:
                from app.services.notifications.dispatcher import NotificationDispatcher

                dispatcher = NotificationDispatcher(db)
                await dispatcher.notify_restart_success(container.name, attempt_number)

            return {"success": True, "health": health_result}

        except OperationalError as e:
            logger.error(f"Database error during restart of {container.name}: {e}")

            log_entry.success = False
            log_entry.error_message = str(e)
            log_entry.completed_at = datetime.now(UTC)
            await db.commit()

            return {"success": False, "error": str(e)}
        except (ImportError, AttributeError) as e:
            logger.error(
                f"Service dependency error during restart of {container.name}: {e}"
            )

            log_entry.success = False
            log_entry.error_message = str(e)
            log_entry.completed_at = datetime.now(UTC)
            await db.commit()

            return {"success": False, "error": str(e)}
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid data during restart of {container.name}: {e}")

            log_entry.success = False
            log_entry.error_message = str(e)
            log_entry.completed_at = datetime.now(UTC)
            await db.commit()

            return {"success": False, "error": str(e)}

    @staticmethod
    async def _execute_docker_compose_restart(
        container: Container, db: AsyncSession
    ) -> dict:
        """Execute docker compose restart command.

        Args:
            container: Container to restart
            db: Database session

        Returns:
            Result dictionary
        """
        start_time = datetime.now(UTC)

        try:
            # Get settings
            docker_socket = await SettingsService.get(
                db, "docker_socket", default="/var/run/docker.sock"
            )
            docker_compose_cmd = await SettingsService.get(
                db, "docker_compose_command", default="docker compose"
            )

            # Build command with explicit project and file flags
            cmd_parts = docker_compose_cmd.split()
            if container.compose_project:
                cmd_parts.extend(["-p", container.compose_project])
            cmd_parts.extend(
                ["-f", container.compose_file, "restart", container.service_name]
            )

            # Format docker socket to DOCKER_HOST environment variable
            docker_host = (
                docker_socket
                if docker_socket.startswith(("tcp://", "unix://"))
                else f"unix://{docker_socket}"
            )

            # Execute with proper DOCKER_HOST environment variable
            import os

            env = os.environ.copy()
            env["DOCKER_HOST"] = docker_host

            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)

            duration = (datetime.now(UTC) - start_time).total_seconds()

            if process.returncode != 0:
                error = stderr.decode().strip() or stdout.decode().strip()
                return {
                    "success": False,
                    "error": error,
                    "command": " ".join(cmd_parts),
                    "duration": duration,
                }

            return {
                "success": True,
                "command": " ".join(cmd_parts),
                "stdout": stdout.decode().strip(),
                "duration": duration,
            }

        except TimeoutError:
            return {
                "success": False,
                "error": "Docker compose restart timed out after 120 seconds",
                "duration": 120.0,
            }
        except OperationalError as e:
            return {
                "success": False,
                "error": f"Database error during restart: {str(e)}",
                "duration": (datetime.now(UTC) - start_time).total_seconds(),
            }
        except (OSError, PermissionError) as e:
            return {
                "success": False,
                "error": f"Process execution error: {str(e)}",
                "duration": (datetime.now(UTC) - start_time).total_seconds(),
            }
        except (ValueError, KeyError, AttributeError) as e:
            return {
                "success": False,
                "error": f"Invalid restart data: {str(e)}",
                "duration": (datetime.now(UTC) - start_time).total_seconds(),
            }

    @staticmethod
    async def _validate_health_check(
        container: Container, timeout: int, db: AsyncSession
    ) -> dict:
        """Validate container health after restart.

        Reuses the existing health check logic from UpdateEngine.

        Args:
            container: Container to check
            timeout: Timeout in seconds
            db: Database session

        Returns:
            Health check result
        """
        result = await UpdateEngine._validate_health_check(container, timeout)
        return {
            "healthy": result.get("success", False),
            "method": result.get("method"),
            "status_code": result.get("status_code"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "error": result.get("error"),
        }


# Singleton instance
restart_service = RestartService()
