"""Service for detecting and tracking HTTP servers running in containers."""

import logging
import re
from datetime import datetime

import docker
import httpx

logger = logging.getLogger(__name__)


class HttpServerScanner:
    """Scanner for detecting HTTP servers running in containers."""

    def __init__(self):
        self.timeout = httpx.Timeout(5.0)
        self.docker_client = docker.from_env()

        # Known HTTP servers and their detection methods
        self.server_patterns = {
            "nginx": {
                "commands": ["nginx -v", "nginx -V"],
                "version_regex": r"nginx/(\d+\.\d+\.\d+)",
                "check_url": "https://nginx.org/en/CHANGES",
                "latest_api": "https://nginx.org/en/download.html",
            },
            "apache": {
                "commands": ["httpd -v", "apache2 -v", "apachectl -v"],
                "version_regex": r"Apache/(\d+\.\d+\.\d+)",
                "check_url": "https://httpd.apache.org/",
                "latest_api": None,
            },
            "caddy": {
                "commands": ["caddy version"],
                "version_regex": r"v?(\d+\.\d+\.\d+)",
                "check_url": "https://github.com/caddyserver/caddy/releases",
                "latest_api": "https://api.github.com/repos/caddyserver/caddy/releases/latest",
            },
            "traefik": {
                "commands": ["traefik version"],
                "version_regex": r"Version:\s*v?(\d+\.\d+\.\d+)",
                "check_url": "https://github.com/traefik/traefik/releases",
                "latest_api": "https://api.github.com/repos/traefik/traefik/releases/latest",
            },
            "granian": {
                "commands": ["granian --version"],
                "version_regex": r"granian\s+v?(\d+\.\d+\.\d+)",
                "check_url": "https://github.com/emmett-framework/granian/releases",
                "latest_api": "https://api.github.com/repos/emmett-framework/granian/releases/latest",
            },
            "lighttpd": {
                "commands": ["lighttpd -v"],
                "version_regex": r"lighttpd/(\d+\.\d+\.\d+)",
                "check_url": "https://www.lighttpd.net/",
                "latest_api": None,
            },
            "httpd": {
                "commands": ["httpd -v"],
                "version_regex": r"Apache/(\d+\.\d+\.\d+)",
                "check_url": "https://httpd.apache.org/",
                "latest_api": None,
            },
        }

        # Process-based detection (for servers running as processes)
        self.process_patterns = {
            "nginx": "nginx",
            "apache": "apache2|httpd",
            "caddy": "caddy",
            "traefik": "traefik",
            "lighttpd": "lighttpd",
            "uvicorn": "uvicorn",
            "gunicorn": "gunicorn",
            "granian": "granian",
            "node": "node",
            "python": "python.*manage.py runserver",
        }

    async def scan_container_http_servers(
        self, container_name: str, container_model=None, db=None
    ) -> list[dict[str, any]]:
        """
        Scan a container for running HTTP servers.

        Args:
            container_name: Name of the container to scan
            container_model: Optional Container database model for dockerfile detection
            db: Optional database session for reading settings

        Returns:
            List of detected HTTP servers with version information
        """
        servers = []

        try:
            container = self.docker_client.containers.get(container_name)

            # Method 0: Check container labels (works even when stopped)
            label_servers = await self._detect_from_labels(container, container_model, db)

            # If container is not running, only use label detection
            if container.status != "running":
                logger.info(
                    f"Container {container_name} is {container.status}, using label-based detection only"
                )
                servers = label_servers
            else:
                # Container is running - use all detection methods
                # Method 1: Check container config (works on stopped too, but redundant with labels)
                config_servers = await self._detect_from_container_config(container)

                # Method 2: Check processes
                process_servers = await self._detect_from_processes(container)

                # Method 3: Try version commands for known servers
                version_servers = await self._detect_from_version_commands(container)

                # Merge results, preferring more detailed detection methods
                servers_dict = {}

                # Add label-detected servers first (base data)
                for server in label_servers:
                    servers_dict[server["name"]] = server

                # Add config-detected servers (may add new servers)
                for server in config_servers:
                    if server["name"] not in servers_dict:
                        servers_dict[server["name"]] = server

                # Add process-detected servers (may add new servers)
                for server in process_servers:
                    if server["name"] not in servers_dict:
                        servers_dict[server["name"]] = server

                # Update with version-detected servers (best data, includes version)
                for server in version_servers:
                    if server["name"] in servers_dict:
                        # Update existing entry with version info
                        servers_dict[server["name"]]["current_version"] = server.get(
                            "current_version"
                        )
                        servers_dict[server["name"]]["detection_method"] = (
                            "version_command"
                        )
                    else:
                        # Add new server
                        servers_dict[server["name"]] = server

                # Convert back to list
                servers = list(servers_dict.values())

            # Detect Dockerfile paths for all detected servers (if not already set)
            # Also read version from Dockerfile if available (source of truth for My Projects)
            for server in servers:
                if not server.get("dockerfile_path"):
                    dockerfile_path, line_number = await self._find_dockerfile_path(
                        container, container_model, db
                    )
                    if dockerfile_path:
                        server["dockerfile_path"] = dockerfile_path
                        server["line_number"] = line_number

                        # Read version from Dockerfile LABEL (source of truth)
                        dockerfile_version = self._read_version_from_dockerfile(
                            dockerfile_path
                        )
                        if dockerfile_version:
                            server["current_version"] = dockerfile_version
                            logger.info(
                                f"Using Dockerfile version {dockerfile_version} for {server['name']} (overriding container version)"
                            )

            # Get latest versions for detected servers
            for server in servers:
                server["latest_version"] = await self._get_latest_version(
                    server["name"], server.get("current_version")
                )
                server["update_available"] = self._check_update_available(
                    server.get("current_version"), server.get("latest_version")
                )

        except docker.errors.NotFound:
            logger.error(f"Container {container_name} not found")
        except docker.errors.APIError as e:
            logger.error(f"Docker API error scanning container {container_name}: {e}")
        except docker.errors.DockerException as e:
            logger.error(f"Docker error scanning container {container_name}: {e}")
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid data scanning container {container_name}: {e}")

        return servers

    async def persist_http_servers(
        self, container_id: int, servers: list[dict], db
    ) -> list:
        """Persist scanned HTTP servers to database.

        Args:
            container_id: Container ID
            servers: List of detected servers from scan_container_http_servers()
            db: Database session

        Returns:
            List of persisted HttpServer model instances with IDs
        """
        from datetime import UTC, datetime

        from app.models.http_server import HttpServer
        from sqlalchemy import select

        def extract_version_prefix(tag: str | None) -> str | None:
            """Extract major.minor version prefix from a tag."""
            if not tag:
                return None
            import re

            match = re.match(r"^(\d+)(?:\.(\d+))?", tag)
            if match:
                major = match.group(1)
                minor = match.group(2)
                if minor:
                    return f"{major}.{minor}"
                return major
            return None

        persisted = []
        for server_data in servers:
            # Check if exists (upsert based on container_id + name)
            result = await db.execute(
                select(HttpServer).where(
                    HttpServer.container_id == container_id,
                    HttpServer.name == server_data["name"],
                )
            )
            server = result.scalar_one_or_none()

            if server:
                # Update existing record
                server.current_version = server_data.get("current_version")
                server.latest_version = server_data.get("latest_version")
                server.update_available = server_data.get("update_available", False)
                server.detection_method = server_data.get("detection_method")
                server.dockerfile_path = server_data.get("dockerfile_path")
                server.line_number = server_data.get("line_number")
                server.last_checked = datetime.now(UTC)

                # Clear ignore if new version beyond ignored version
                if server.ignored and server.latest_version != server.ignored_version:
                    version_prefix = extract_version_prefix(server.latest_version)
                    if version_prefix != server.ignored_version_prefix:
                        server.ignored = False
                        server.ignored_version = None
                        server.ignored_version_prefix = None
                        server.ignored_by = None
                        server.ignored_at = None
                        server.ignored_reason = None
                        logger.info(
                            f"Cleared ignore for {server.name} (version changed from {server.ignored_version} to {server.latest_version})"
                        )
            else:
                # Create new record
                server = HttpServer(
                    container_id=container_id,
                    name=server_data["name"],
                    current_version=server_data.get("current_version"),
                    latest_version=server_data.get("latest_version"),
                    update_available=server_data.get("update_available", False),
                    detection_method=server_data.get("detection_method"),
                    dockerfile_path=server_data.get("dockerfile_path"),
                    line_number=server_data.get("line_number"),
                    last_checked=datetime.now(UTC),
                )
                db.add(server)
                logger.info(
                    f"Created new HTTP server record: {server.name} for container {container_id}"
                )

            persisted.append(server)

        # Commit and refresh to get IDs
        await db.commit()

        for server in persisted:
            await db.refresh(server)

        return persisted

    async def _detect_from_processes(self, container) -> list[dict[str, any]]:
        """Detect HTTP servers from running processes."""
        servers = []

        try:
            # Try different process listing commands
            commands = [
                ["ps", "aux"],
                ["ps", "-ef"],
                ["ps"],
            ]

            output = None
            for cmd in commands:
                try:
                    result = container.exec_run(cmd, demux=False)
                    if result.exit_code == 0:
                        output = (
                            result.output.decode("utf-8")
                            if isinstance(result.output, bytes)
                            else result.output
                        )
                        break
                except Exception:
                    # Command not available in container, try next
                    continue

            # If ps is not available, try checking /proc
            if not output:
                try:
                    result = container.exec_run(
                        ["sh", "-c", 'cat /proc/*/cmdline 2>/dev/null | tr "\\0" " "'],
                        demux=False,
                    )
                    if result.exit_code == 0:
                        output = (
                            result.output.decode("utf-8")
                            if isinstance(result.output, bytes)
                            else result.output
                        )
                except Exception:
                    # /proc not accessible
                    pass

            if not output:
                logger.debug(f"Could not get process list for {container.name}")
                return servers

            for server_name, pattern in self.process_patterns.items():
                if re.search(pattern, output, re.IGNORECASE):
                    servers.append(
                        {
                            "name": server_name,
                            "current_version": None,
                            "detection_method": "process",
                            "last_checked": datetime.utcnow(),
                        }
                    )
                    logger.info(
                        f"Detected {server_name} from process list in {container.name}"
                    )

        except docker.errors.APIError as e:
            logger.debug(f"Docker API error detecting from processes: {e}")
        except docker.errors.DockerException as e:
            logger.debug(f"Docker error detecting from processes: {e}")
        except (UnicodeDecodeError, ValueError, AttributeError) as e:
            logger.debug(f"Failed to parse process list: {e}")

        return servers

    async def _detect_from_version_commands(self, container) -> list[dict[str, any]]:
        """Detect HTTP servers by running version commands."""
        servers = []

        for server_name, config in self.server_patterns.items():
            for cmd in config["commands"]:
                try:
                    # Execute version command
                    result = container.exec_run(cmd.split(), demux=False)

                    if result.exit_code == 0:
                        output = (
                            result.output.decode("utf-8")
                            if isinstance(result.output, bytes)
                            else result.output
                        )

                        # Extract version
                        match = re.search(config["version_regex"], output)
                        if match:
                            version = match.group(1)
                            servers.append(
                                {
                                    "name": server_name,
                                    "current_version": version,
                                    "detection_method": "version_command",
                                    "last_checked": datetime.utcnow(),
                                }
                            )
                            logger.info(
                                f"Detected {server_name} v{version} in {container.name}"
                            )
                            break  # Found version, no need to try other commands

                except docker.errors.APIError as e:
                    logger.debug(
                        f"Docker API error running '{cmd}' for {server_name}: {e}"
                    )
                    continue
                except docker.errors.DockerException as e:
                    logger.debug(f"Docker error running '{cmd}' for {server_name}: {e}")
                    continue
                except (UnicodeDecodeError, ValueError, AttributeError) as e:
                    logger.debug(
                        f"Failed to parse output of '{cmd}' for {server_name}: {e}"
                    )
                    continue

        return servers

    async def _get_latest_version(
        self, server_name: str, current_version: str | None
    ) -> str | None:
        """Get the latest version for a specific HTTP server."""
        config = self.server_patterns.get(server_name)
        if not config or not config.get("latest_api"):
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                from urllib.parse import urlparse

                parsed = urlparse(config["latest_api"])
                if parsed.netloc == "api.github.com" or parsed.netloc == "github.com":
                    # GitHub releases API
                    response = await client.get(
                        config["latest_api"],
                        headers={"Accept": "application/vnd.github.v3+json"},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        tag_name = data.get("tag_name", "")
                        # Remove 'v' prefix if present
                        version = tag_name.lstrip("v")
                        return version

                # Add other API patterns here as needed

        except httpx.HTTPStatusError as e:
            logger.debug(f"HTTP error fetching latest version for {server_name}: {e}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug(
                f"Connection error fetching latest version for {server_name}: {e}"
            )
        except (ValueError, KeyError, AttributeError) as e:
            logger.debug(f"Failed to parse version data for {server_name}: {e}")

        return None

    def _check_update_available(
        self, current: str | None, latest: str | None
    ) -> bool:
        """Check if an update is available based on version comparison."""
        if not current or not latest:
            return False

        try:
            # Simple version comparison
            current_parts = [int(x) for x in current.split(".")[:3]]
            latest_parts = [int(x) for x in latest.split(".")[:3]]

            # Pad to 3 parts
            while len(current_parts) < 3:
                current_parts.append(0)
            while len(latest_parts) < 3:
                latest_parts.append(0)

            return latest_parts > current_parts
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(
                f"Failed to parse versions for comparison ({current} vs {latest}): {e}"
            )
            return False

    def _calculate_severity(
        self, current: str | None, latest: str | None, has_update: bool
    ) -> str:
        """Calculate severity of update based on semver difference."""
        if not has_update or not current or not latest:
            return "info"

        try:
            current_parts = [int(x) for x in current.split(".")[:3]]
            latest_parts = [int(x) for x in latest.split(".")[:3]]

            # Pad to 3 parts
            while len(current_parts) < 3:
                current_parts.append(0)
            while len(latest_parts) < 3:
                latest_parts.append(0)

            # Major version change (breaking changes expected per semver)
            if latest_parts[0] > current_parts[0]:
                return "high"
            # Minor version change (backwards-compatible features)
            elif latest_parts[1] > current_parts[1]:
                return "low"
            # Patch version change (backwards-compatible bug fixes)
            else:
                return "info"
        except (ValueError, IndexError, TypeError):
            # If version parsing fails, default to info severity
            return "info"

    async def _detect_from_labels(
        self, container, container_model=None, db=None
    ) -> list[dict[str, any]]:
        """Detect HTTP servers from container labels.

        Args:
            container: Docker container object
            container_model: Optional Container database model with is_my_project flag
            db: Optional database session for reading settings

        Returns:
            List of server info dicts with dockerfile_path populated if available
        """
        servers = []

        try:
            labels = container.labels or {}

            # Check for http.server.* labels
            server_name = labels.get("http.server.name")
            if server_name:
                server_info = {
                    "name": server_name.lower(),
                    "current_version": labels.get("http.server.version"),
                    "detection_method": "labels",
                    "last_checked": datetime.utcnow(),
                }

                # Detect Dockerfile path for "My Projects" containers
                dockerfile_path, line_number = await self._find_dockerfile_path(
                    container, container_model, db
                )
                if dockerfile_path:
                    server_info["dockerfile_path"] = dockerfile_path
                    server_info["line_number"] = line_number

                servers.append(server_info)
                logger.info(f"Detected {server_name} from labels in {container.name}")

        except (AttributeError, TypeError) as e:
            logger.debug(f"Failed to detect from labels: {e}")

        return servers

    def _read_version_from_dockerfile(self, dockerfile_path: str) -> str | None:
        """Read http.server.version from Dockerfile LABEL.

        Args:
            dockerfile_path: Path to the Dockerfile

        Returns:
            Version string or None
        """
        try:
            with open(dockerfile_path, encoding="utf-8") as f:
                for line in f:
                    if 'LABEL http.server.version=' in line:
                        # Extract version from: LABEL http.server.version="2.6.1"
                        match = re.search(r'LABEL\s+http\.server\.version="([^"]+)"', line)
                        if match:
                            return match.group(1)
        except (OSError, IOError) as e:
            logger.debug(f"Error reading version from Dockerfile {dockerfile_path}: {e}")
        return None

    async def _find_dockerfile_path(
        self, container, container_model=None, db=None
    ) -> tuple[str | None, int | None]:
        """Find Dockerfile path and line number for http.server.version label.

        For "My Projects" containers, the Dockerfile is located at:
        {projects_directory}/{project_name}/Dockerfile

        Args:
            container: Docker container object
            container_model: Optional Container database model
            db: Database session (required to read projects_directory setting)

        Returns:
            Tuple of (dockerfile_path, line_number) or (None, None)
        """
        from pathlib import Path
        from app.services.settings_service import SettingsService

        try:
            # Check if this is a "My Project" container
            is_my_project = (
                container_model and getattr(container_model, "is_my_project", False)
            )

            if not is_my_project:
                logger.debug(
                    f"Container {container.name} is not a My Project, skipping Dockerfile detection"
                )
                return None, None

            # Get projects directory from settings (fallback to /projects)
            if db:
                projects_dir = await SettingsService.get(db, "projects_directory")
            else:
                projects_dir = "/projects"  # Fallback if no db session
                logger.warning("No db session provided, using default projects_directory: /projects")

            # Extract project name from container name
            # Examples: "familycircle-dev" -> "familycircle", "mygarage" -> "mygarage"
            project_name = container.name.split("-")[0]

            # Construct Dockerfile path using setting
            dockerfile_path = f"{projects_dir}/{project_name}/Dockerfile"

            # Verify file exists
            if not Path(dockerfile_path).exists():
                logger.warning(
                    f"Expected Dockerfile not found at {dockerfile_path} for container {container.name}"
                )
                return None, None

            # Find line number of http.server.version label
            line_number = None
            with open(dockerfile_path, encoding="utf-8") as f:
                for i, line in enumerate(f, start=1):
                    if 'LABEL http.server.version=' in line:
                        line_number = i
                        break

            if line_number:
                logger.info(
                    f"Found Dockerfile at {dockerfile_path}:{line_number} for {container.name}"
                )
            else:
                logger.warning(
                    f"Could not find http.server.version label in {dockerfile_path}"
                )

            return dockerfile_path, line_number

        except (OSError, IOError) as e:
            logger.error(f"Error reading Dockerfile: {e}")
            return None, None
        except (AttributeError, IndexError) as e:
            logger.debug(f"Error parsing container name: {e}")
            return None, None

    async def _detect_from_container_config(self, container) -> list[dict[str, any]]:
        """Detect HTTP servers from container config without exec."""
        servers = []

        try:
            # Get container config
            config = container.attrs.get("Config", {})

            # Check CMD and Entrypoint
            cmd_parts = config.get("Cmd", []) or []
            entrypoint_parts = config.get("Entrypoint", []) or []

            # Combine into single command string
            full_cmd = " ".join(entrypoint_parts + cmd_parts)

            # Check against patterns
            for server_name, pattern in self.process_patterns.items():
                if re.search(pattern, full_cmd, re.IGNORECASE):
                    server_info = {
                        "name": server_name,
                        "current_version": None,
                        "detection_method": "container_config",
                        "last_checked": datetime.utcnow(),
                    }

                    # Try to extract version from command args (rare but possible)
                    version_match = re.search(
                        r"--version[=\s]+(\d+\.\d+\.\d+)", full_cmd
                    )
                    if version_match:
                        server_info["current_version"] = version_match.group(1)

                    servers.append(server_info)
                    logger.info(
                        f"Detected {server_name} from container config in {container.name}"
                    )

        except (AttributeError, TypeError, KeyError) as e:
            logger.debug(f"Failed to detect from container config: {e}")

        return servers


# Global scanner instance
http_scanner = HttpServerScanner()
