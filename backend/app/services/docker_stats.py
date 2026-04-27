"""Docker stats service for real-time container metrics."""

import asyncio
import json
import logging

from app.services.docker_access import docker_subprocess_env, resolve_docker_url_sync

logger = logging.getLogger(__name__)

# Resolved once at import; reconnect() on ContainerMonitorService
# covers proxy restarts. For a full runtime-change story, see
# docker_access.py docstring.
_DOCKER_ENV = docker_subprocess_env(resolve_docker_url_sync())


class DockerStatsService:
    """Service for getting Docker container metrics."""

    @staticmethod
    async def list_running_container_names() -> set[str] | None:
        """Return the set of currently-running container names (host docker view).

        One subprocess call (~10ms) — used by metrics_collector to pre-filter
        before the batched ``docker stats`` call (which aborts the entire
        batch if any name is unknown).

        Returns:
            Set of container names, or None on error.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "--format",
                "{{.Names}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_DOCKER_ENV,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            if process.returncode != 0:
                logger.warning(
                    "docker ps failed: %s",
                    stderr.decode("utf-8", errors="replace").strip(),
                )
                return None
            names = {
                line.strip()
                for line in stdout.decode("utf-8", errors="replace").splitlines()
                if line.strip()
            }
            return names
        except TimeoutError:
            logger.warning("Timeout listing running containers")
            return None
        except (OSError, PermissionError) as e:
            logger.warning("Process error listing running containers: %s", e)
            return None

    @staticmethod
    async def get_batched_stats(container_names: list[str]) -> dict[str, dict]:
        """Get stats for many containers in ONE ``docker stats`` subprocess.

        Massively faster than per-container calls — 42 containers in ~2s vs
        ~22s with 4-way concurrency. The trade-off: ``docker stats`` aborts
        the whole batch if ANY name is missing/stopped, so callers MUST
        pre-filter using :meth:`list_running_container_names`.

        Args:
            container_names: Names of currently-running containers. Must be
                a non-empty list of names that exist; otherwise the entire
                call fails and an empty dict is returned.

        Returns:
            Dict mapping container name → parsed stats dict. Containers that
            failed to parse are simply omitted. Empty dict on subprocess
            failure (with a warning logged).
        """
        if not container_names:
            return {}
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "stats",
                *container_names,
                "--no-stream",
                "--format",
                "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_DOCKER_ENV,
            )
            # Each container needs ~2s of sample window; allow generous timeout
            # for very large batches but not unbounded.
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)
            if process.returncode != 0:
                logger.warning(
                    "Batched docker stats failed (the batch aborted — typically a "
                    "container in the list disappeared between ps and stats): %s",
                    stderr.decode("utf-8", errors="replace").strip(),
                )
                return {}
            out: dict[str, dict] = {}
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning("Skipping unparseable stats line: %s — %r", e, line)
                    continue
                name = raw.get("Name") or raw.get("Container")
                if not name:
                    continue
                mem_usage_str = raw.get("MemUsage", "0B / 0B")
                net_io_str = raw.get("NetIO", "0B / 0B")
                block_io_str = raw.get("BlockIO", "0B / 0B")
                try:
                    out[name] = {
                        "cpu_percent": DockerStatsService._parse_percent(raw.get("CPUPerc", "0%")),
                        "memory_usage": DockerStatsService._parse_bytes(
                            DockerStatsService._extract_memory_usage(mem_usage_str)
                        ),
                        "memory_percent": DockerStatsService._parse_percent(
                            raw.get("MemPerc", "0%")
                        ),
                        "memory_limit": DockerStatsService._parse_bytes(
                            DockerStatsService._extract_memory_limit(mem_usage_str)
                        ),
                        "network_rx": DockerStatsService._parse_bytes(
                            DockerStatsService._extract_network_rx(net_io_str)
                        ),
                        "network_tx": DockerStatsService._parse_bytes(
                            DockerStatsService._extract_network_tx(net_io_str)
                        ),
                        "block_read": DockerStatsService._parse_bytes(
                            DockerStatsService._extract_block_read(block_io_str)
                        ),
                        "block_write": DockerStatsService._parse_bytes(
                            DockerStatsService._extract_block_write(block_io_str)
                        ),
                        "pids": int(raw.get("PIDs", "0") or 0),
                    }
                except (ValueError, KeyError, AttributeError) as e:
                    logger.warning("Invalid stats data for %s: %s", name, e)
                    continue
            return out
        except TimeoutError:
            logger.warning(
                "Timeout running batched docker stats for %d containers", len(container_names)
            )
            return {}
        except (OSError, PermissionError) as e:
            logger.warning("Process error running batched docker stats: %s", e)
            return {}

    @staticmethod
    async def get_container_stats(container_name: str) -> dict | None:
        """Get real-time stats for a container.

        Args:
            container_name: Name of the container

        Returns:
            Dictionary with CPU, memory, network, and block I/O stats
            Returns None if container not found or not running
        """
        try:
            # Run docker stats with JSON format (one-shot)
            process = await asyncio.create_subprocess_exec(
                "docker",
                "stats",
                container_name,
                "--no-stream",
                "--format",
                "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_DOCKER_ENV,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                logger.warning(f"Failed to get stats for {container_name}: {error_msg}")
                return None

            # Parse JSON output
            stats_json = stdout.decode().strip()
            if not stats_json:
                return None

            stats = json.loads(stats_json)

            # Parse the stats into a clean format
            mem_usage_str = stats.get("MemUsage", "0B / 0B")
            net_io_str = stats.get("NetIO", "0B / 0B")
            block_io_str = stats.get("BlockIO", "0B / 0B")

            return {
                "cpu_percent": DockerStatsService._parse_percent(stats.get("CPUPerc", "0%")),
                "memory_usage": DockerStatsService._parse_bytes(
                    DockerStatsService._extract_memory_usage(mem_usage_str)
                ),
                "memory_percent": DockerStatsService._parse_percent(stats.get("MemPerc", "0%")),
                "memory_limit": DockerStatsService._parse_bytes(
                    DockerStatsService._extract_memory_limit(mem_usage_str)
                ),
                "network_rx": DockerStatsService._parse_bytes(
                    DockerStatsService._extract_network_rx(net_io_str)
                ),
                "network_tx": DockerStatsService._parse_bytes(
                    DockerStatsService._extract_network_tx(net_io_str)
                ),
                "block_read": DockerStatsService._parse_bytes(
                    DockerStatsService._extract_block_read(block_io_str)
                ),
                "block_write": DockerStatsService._parse_bytes(
                    DockerStatsService._extract_block_write(block_io_str)
                ),
                "pids": int(stats.get("PIDs", "0") or 0),
            }

        except TimeoutError:
            logger.warning(f"Timeout getting stats for {container_name}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse stats JSON: {e}")
            return None
        except (OSError, PermissionError) as e:
            logger.error(f"Process execution error getting stats for {container_name}: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid stats data for {container_name}: {e}")
            return None

    @staticmethod
    def _parse_percent(percent_str: str) -> float:
        """Parse percentage string like '12.34%' to float."""
        try:
            return float(percent_str.rstrip("%"))
        except ValueError, AttributeError:
            return 0.0

    @staticmethod
    def _parse_bytes(size_str: str) -> int:
        """Parse byte size string like '512MB', '1.5GB' to bytes.

        Args:
            size_str: Size string (e.g., '512MB', '1.5GB', '2.3KiB')

        Returns:
            Size in bytes as integer
        """
        if not size_str or size_str == "N/A":
            return 0

        size_str = size_str.strip()

        # Units mapping (case insensitive)
        units = {
            "B": 1,
            "KB": 1000,
            "MB": 1000**2,
            "GB": 1000**3,
            "TB": 1000**4,
            "KIB": 1024,
            "MIB": 1024**2,
            "GIB": 1024**3,
            "TIB": 1024**4,
        }

        try:
            # Extract number and unit
            import re

            match = re.match(r"^([\d.]+)\s*([A-Za-z]+)?$", size_str)
            if not match:
                return 0

            number = float(match.group(1))
            unit = match.group(2) if match.group(2) else "B"
            unit = unit.upper()

            # Get multiplier
            multiplier = units.get(unit, 1)

            return int(number * multiplier)
        except ValueError, AttributeError:
            return 0

    @staticmethod
    def _extract_memory_usage(mem_usage: str) -> str:
        """Extract memory usage from 'used / limit' string."""
        try:
            parts = mem_usage.split(" / ")
            return parts[0].strip() if len(parts) > 0 else "0B"
        except Exception:
            return "0B"

    @staticmethod
    def _extract_memory_limit(mem_usage: str) -> str:
        """Extract memory limit from 'used / limit' string."""
        try:
            parts = mem_usage.split(" / ")
            return parts[1] if len(parts) > 1 else "N/A"
        except Exception:
            return "N/A"

    @staticmethod
    def _extract_network_rx(net_io: str) -> str:
        """Extract network RX (received) from 'RX / TX' string."""
        try:
            parts = net_io.split(" / ")
            return parts[0].strip() if len(parts) > 0 else "0B"
        except Exception:
            return "0B"

    @staticmethod
    def _extract_network_tx(net_io: str) -> str:
        """Extract network TX (transmitted) from 'RX / TX' string."""
        try:
            parts = net_io.split(" / ")
            return parts[1].strip() if len(parts) > 1 else "0B"
        except Exception:
            return "0B"

    @staticmethod
    def _extract_block_read(block_io: str) -> str:
        """Extract block read from 'read / write' string."""
        try:
            parts = block_io.split(" / ")
            return parts[0].strip() if len(parts) > 0 else "0B"
        except Exception:
            return "0B"

    @staticmethod
    def _extract_block_write(block_io: str) -> str:
        """Extract block write from 'read / write' string."""
        try:
            parts = block_io.split(" / ")
            return parts[1].strip() if len(parts) > 1 else "0B"
        except Exception:
            return "0B"

    @staticmethod
    async def get_container_logs(
        container_name: str,
        tail: int = 100,
        since: str | None = None,
        follow: bool = False,
        docker_host: str | None = None,
    ) -> str | None:
        """Get logs from a container.

        Args:
            container_name: Name of the container
            tail: Number of lines to return from end of logs (default: 100)
            since: Only return logs since this timestamp (e.g., '5m', '1h', '2024-01-01')
            follow: Stream logs in real-time (not recommended for API calls)
            docker_host: Docker host URL (optional, uses DOCKER_HOST env if not provided)

        Returns:
            Log output as string, or None if error
        """
        process = None
        try:
            cmd = ["docker", "logs", "--timestamps"]

            # Add tail parameter
            if tail:
                cmd.extend(["--tail", str(tail)])

            # Add since parameter
            if since:
                cmd.extend(["--since", since])

            # Add follow if requested (careful with this in API)
            if follow:
                cmd.append("--follow")

            cmd.append(container_name)

            # Use provided docker_host or fall back to resolved default
            env = docker_subprocess_env(docker_host) if docker_host else _DOCKER_ENV

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Combine stderr with stdout
                env=env,
            )

            timeout = 30.0 if follow else 10.0
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)

            if process.returncode != 0:
                logger.warning(
                    f"Failed to get logs for {container_name} (exit code: {process.returncode})"
                )
                return None

            return stdout.decode("utf-8", errors="replace")

        except TimeoutError:
            logger.warning(f"Timeout getting logs for {container_name}")
            # Kill the process if it's still running
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            return None
        except (OSError, PermissionError) as e:
            logger.error(f"Process execution error getting logs for {container_name}: {e}")
            return None
        except (UnicodeDecodeError, ValueError) as e:
            logger.error(f"Failed to decode logs for {container_name}: {e}")
            return None

    @staticmethod
    async def check_container_running(container_name: str) -> bool:
        """Check if a container is currently running.

        Args:
            container_name: Name of the container

        Returns:
            True if container is running, False otherwise
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_DOCKER_ENV,
            )

            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5.0)

            if process.returncode != 0:
                return False

            output = stdout.decode().strip()
            return output.lower() == "true"

        except (OSError, PermissionError) as e:
            logger.debug(f"Process execution error checking if {container_name} is running: {e}")
            return False
        except (UnicodeDecodeError, ValueError, AttributeError) as e:
            logger.debug(f"Failed to parse container status for {container_name}: {e}")
            return False

    @staticmethod
    async def get_container_exit_info(container_name: str) -> dict | None:
        """Get exit code and failure details for a container.

        Args:
            container_name: Name of the container

        Returns:
            Dictionary with exit information or None if error
        """
        try:
            cmd = ["docker", "inspect", "--format", "{{json .State}}", container_name]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_DOCKER_ENV,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)

            if process.returncode != 0:
                return None

            state = json.loads(stdout.decode())

            return {
                "exit_code": state.get("ExitCode"),
                "oom_killed": state.get("OOMKilled", False),
                "error": state.get("Error", ""),
                "finished_at": state.get("FinishedAt"),
                "restart_count": state.get("RestartCount", 0),
                "status": state.get("Status"),
                "running": state.get("Running", False),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse exit info JSON for {container_name}: {e}")
            return None
        except (OSError, PermissionError) as e:
            logger.error(f"Process execution error getting exit info for {container_name}: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid exit info data for {container_name}: {e}")
            return None

    @staticmethod
    async def get_restart_policy(container_name: str) -> str:
        """Get the Docker restart policy for a container.

        Args:
            container_name: Name of the container

        Returns:
            Restart policy name ('no', 'on-failure', 'always', 'unless-stopped')
            Returns 'manual' (default) if container not found or error
        """
        try:
            cmd = [
                "docker",
                "inspect",
                "--format",
                "{{.HostConfig.RestartPolicy.Name}}",
                container_name,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_DOCKER_ENV,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)

            if process.returncode != 0:
                logger.debug(f"Container {container_name} not found in Docker runtime")
                return "manual"

            policy = stdout.decode().strip()

            # Docker returns empty string for "no" policy, or the policy name
            if not policy or policy == "no":
                return "manual"

            return policy

        except (OSError, PermissionError) as e:
            logger.debug(
                f"Process execution error getting restart policy for {container_name}: {e}"
            )
            return "manual"
        except (UnicodeDecodeError, ValueError, AttributeError) as e:
            logger.debug(f"Failed to parse restart policy for {container_name}: {e}")
            return "manual"


# Singleton instance
docker_stats_service = DockerStatsService()
