"""Service for detecting and tracking HTTP servers running in containers."""

import logging
import re
from typing import Dict, List, Optional
import httpx
import docker
from datetime import datetime

logger = logging.getLogger(__name__)


class HttpServerScanner:
    """Scanner for detecting HTTP servers running in containers."""

    def __init__(self):
        self.timeout = httpx.Timeout(5.0)
        self.docker_client = docker.from_env()

        # Known HTTP servers and their detection methods
        self.server_patterns = {
            'nginx': {
                'commands': ['nginx -v', 'nginx -V'],
                'version_regex': r'nginx/(\d+\.\d+\.\d+)',
                'check_url': 'https://nginx.org/en/CHANGES',
                'latest_api': 'https://nginx.org/en/download.html',
            },
            'apache': {
                'commands': ['httpd -v', 'apache2 -v', 'apachectl -v'],
                'version_regex': r'Apache/(\d+\.\d+\.\d+)',
                'check_url': 'https://httpd.apache.org/',
                'latest_api': None,
            },
            'caddy': {
                'commands': ['caddy version'],
                'version_regex': r'v?(\d+\.\d+\.\d+)',
                'check_url': 'https://github.com/caddyserver/caddy/releases',
                'latest_api': 'https://api.github.com/repos/caddyserver/caddy/releases/latest',
            },
            'traefik': {
                'commands': ['traefik version'],
                'version_regex': r'Version:\s*v?(\d+\.\d+\.\d+)',
                'check_url': 'https://github.com/traefik/traefik/releases',
                'latest_api': 'https://api.github.com/repos/traefik/traefik/releases/latest',
            },
            'granian': {
                'commands': ['granian --version'],
                'version_regex': r'granian\s+v?(\d+\.\d+\.\d+)',
                'check_url': 'https://github.com/emmett-framework/granian/releases',
                'latest_api': 'https://api.github.com/repos/emmett-framework/granian/releases/latest',
            },
            'lighttpd': {
                'commands': ['lighttpd -v'],
                'version_regex': r'lighttpd/(\d+\.\d+\.\d+)',
                'check_url': 'https://www.lighttpd.net/',
                'latest_api': None,
            },
            'httpd': {
                'commands': ['httpd -v'],
                'version_regex': r'Apache/(\d+\.\d+\.\d+)',
                'check_url': 'https://httpd.apache.org/',
                'latest_api': None,
            },
        }

        # Process-based detection (for servers running as processes)
        self.process_patterns = {
            'nginx': 'nginx',
            'apache': 'apache2|httpd',
            'caddy': 'caddy',
            'traefik': 'traefik',
            'lighttpd': 'lighttpd',
            'uvicorn': 'uvicorn',
            'gunicorn': 'gunicorn',
            'granian': 'granian',
            'node': 'node',
            'python': 'python.*manage.py runserver',
        }

    async def scan_container_http_servers(
        self, container_name: str
    ) -> List[Dict[str, any]]:
        """
        Scan a container for running HTTP servers.

        Args:
            container_name: Name of the container to scan

        Returns:
            List of detected HTTP servers with version information
        """
        servers = []

        try:
            container = self.docker_client.containers.get(container_name)

            # Method 0: Check container labels (works even when stopped)
            label_servers = await self._detect_from_labels(container)

            # If container is not running, only use label detection
            if container.status != 'running':
                logger.info(f"Container {container_name} is {container.status}, using label-based detection only")
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
                    servers_dict[server['name']] = server

                # Add config-detected servers (may add new servers)
                for server in config_servers:
                    if server['name'] not in servers_dict:
                        servers_dict[server['name']] = server

                # Add process-detected servers (may add new servers)
                for server in process_servers:
                    if server['name'] not in servers_dict:
                        servers_dict[server['name']] = server

                # Update with version-detected servers (best data, includes version)
                for server in version_servers:
                    if server['name'] in servers_dict:
                        # Update existing entry with version info
                        servers_dict[server['name']]['current_version'] = server.get('current_version')
                        servers_dict[server['name']]['detection_method'] = 'version_command'
                    else:
                        # Add new server
                        servers_dict[server['name']] = server

                # Convert back to list
                servers = list(servers_dict.values())

            # Get latest versions for detected servers
            for server in servers:
                server['latest_version'] = await self._get_latest_version(
                    server['name'], server.get('current_version')
                )
                server['update_available'] = self._check_update_available(
                    server.get('current_version'),
                    server.get('latest_version')
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

    async def _detect_from_processes(self, container) -> List[Dict[str, any]]:
        """Detect HTTP servers from running processes."""
        servers = []

        try:
            # Try different process listing commands
            commands = [
                ['ps', 'aux'],
                ['ps', '-ef'],
                ['ps'],
            ]

            output = None
            for cmd in commands:
                try:
                    result = container.exec_run(cmd, demux=False)
                    if result.exit_code == 0:
                        output = result.output.decode('utf-8') if isinstance(result.output, bytes) else result.output
                        break
                except Exception:
                    # Command not available in container, try next
                    continue

            # If ps is not available, try checking /proc
            if not output:
                try:
                    result = container.exec_run(['sh', '-c', 'cat /proc/*/cmdline 2>/dev/null | tr "\\0" " "'], demux=False)
                    if result.exit_code == 0:
                        output = result.output.decode('utf-8') if isinstance(result.output, bytes) else result.output
                except Exception:
                    # /proc not accessible
                    pass

            if not output:
                logger.debug(f"Could not get process list for {container.name}")
                return servers

            for server_name, pattern in self.process_patterns.items():
                if re.search(pattern, output, re.IGNORECASE):
                    servers.append({
                        'name': server_name,
                        'current_version': None,
                        'detection_method': 'process',
                        'last_checked': datetime.utcnow(),
                    })
                    logger.info(f"Detected {server_name} from process list in {container.name}")

        except docker.errors.APIError as e:
            logger.debug(f"Docker API error detecting from processes: {e}")
        except docker.errors.DockerException as e:
            logger.debug(f"Docker error detecting from processes: {e}")
        except (UnicodeDecodeError, ValueError, AttributeError) as e:
            logger.debug(f"Failed to parse process list: {e}")

        return servers

    async def _detect_from_version_commands(self, container) -> List[Dict[str, any]]:
        """Detect HTTP servers by running version commands."""
        servers = []

        for server_name, config in self.server_patterns.items():
            for cmd in config['commands']:
                try:
                    # Execute version command
                    result = container.exec_run(cmd.split(), demux=False)

                    if result.exit_code == 0:
                        output = result.output.decode('utf-8') if isinstance(result.output, bytes) else result.output

                        # Extract version
                        match = re.search(config['version_regex'], output)
                        if match:
                            version = match.group(1)
                            servers.append({
                                'name': server_name,
                                'current_version': version,
                                'detection_method': 'version_command',
                                'last_checked': datetime.utcnow(),
                            })
                            logger.info(f"Detected {server_name} v{version} in {container.name}")
                            break  # Found version, no need to try other commands

                except docker.errors.APIError as e:
                    logger.debug(f"Docker API error running '{cmd}' for {server_name}: {e}")
                    continue
                except docker.errors.DockerException as e:
                    logger.debug(f"Docker error running '{cmd}' for {server_name}: {e}")
                    continue
                except (UnicodeDecodeError, ValueError, AttributeError) as e:
                    logger.debug(f"Failed to parse output of '{cmd}' for {server_name}: {e}")
                    continue

        return servers

    async def _get_latest_version(
        self, server_name: str, current_version: Optional[str]
    ) -> Optional[str]:
        """Get the latest version for a specific HTTP server."""
        config = self.server_patterns.get(server_name)
        if not config or not config.get('latest_api'):
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                from urllib.parse import urlparse
                parsed = urlparse(config['latest_api'])
                if parsed.netloc == 'api.github.com' or parsed.netloc == 'github.com':
                    # GitHub releases API
                    response = await client.get(
                        config['latest_api'],
                        headers={'Accept': 'application/vnd.github.v3+json'}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        tag_name = data.get('tag_name', '')
                        # Remove 'v' prefix if present
                        version = tag_name.lstrip('v')
                        return version

                # Add other API patterns here as needed

        except httpx.HTTPStatusError as e:
            logger.debug(f"HTTP error fetching latest version for {server_name}: {e}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.debug(f"Connection error fetching latest version for {server_name}: {e}")
        except (ValueError, KeyError, AttributeError) as e:
            logger.debug(f"Failed to parse version data for {server_name}: {e}")

        return None

    def _check_update_available(
        self, current: Optional[str], latest: Optional[str]
    ) -> bool:
        """Check if an update is available based on version comparison."""
        if not current or not latest:
            return False

        try:
            # Simple version comparison
            current_parts = [int(x) for x in current.split('.')[:3]]
            latest_parts = [int(x) for x in latest.split('.')[:3]]

            # Pad to 3 parts
            while len(current_parts) < 3:
                current_parts.append(0)
            while len(latest_parts) < 3:
                latest_parts.append(0)

            return latest_parts > current_parts
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Failed to parse versions for comparison ({current} vs {latest}): {e}")
            return False

    def _calculate_severity(
        self, current: Optional[str], latest: Optional[str], has_update: bool
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

    async def _detect_from_labels(self, container) -> List[Dict[str, any]]:
        """Detect HTTP servers from container labels."""
        servers = []

        try:
            labels = container.labels or {}

            # Check for http.server.* labels
            server_name = labels.get('http.server.name')
            if server_name:
                server_info = {
                    'name': server_name.lower(),
                    'current_version': labels.get('http.server.version'),
                    'detection_method': 'labels',
                    'last_checked': datetime.utcnow(),
                }
                servers.append(server_info)
                logger.info(f"Detected {server_name} from labels in {container.name}")

        except (AttributeError, TypeError) as e:
            logger.debug(f"Failed to detect from labels: {e}")

        return servers

    async def _detect_from_container_config(self, container) -> List[Dict[str, any]]:
        """Detect HTTP servers from container config without exec."""
        servers = []

        try:
            # Get container config
            config = container.attrs.get('Config', {})

            # Check CMD and Entrypoint
            cmd_parts = config.get('Cmd', []) or []
            entrypoint_parts = config.get('Entrypoint', []) or []

            # Combine into single command string
            full_cmd = ' '.join(entrypoint_parts + cmd_parts)

            # Check against patterns
            for server_name, pattern in self.process_patterns.items():
                if re.search(pattern, full_cmd, re.IGNORECASE):
                    server_info = {
                        'name': server_name,
                        'current_version': None,
                        'detection_method': 'container_config',
                        'last_checked': datetime.utcnow(),
                    }

                    # Try to extract version from command args (rare but possible)
                    version_match = re.search(r'--version[=\s]+(\d+\.\d+\.\d+)', full_cmd)
                    if version_match:
                        server_info['current_version'] = version_match.group(1)

                    servers.append(server_info)
                    logger.info(f"Detected {server_name} from container config in {container.name}")

        except (AttributeError, TypeError, KeyError) as e:
            logger.debug(f"Failed to detect from container config: {e}")

        return servers


# Global scanner instance
http_scanner = HttpServerScanner()
