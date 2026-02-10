"""VulnForge API client for vulnerability data."""

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def create_vulnforge_client(db: AsyncSession) -> "VulnForgeClient | None":
    """Create a VulnForge client from database settings.

    Shared factory used by scan_service and update_engine. Checks that
    VulnForge integration is enabled and URL is configured, then builds
    a client with the correct auth settings.

    Args:
        db: Database session for reading settings

    Returns:
        VulnForgeClient instance or None if disabled/not configured
    """
    from app.services.settings_service import SettingsService

    vulnforge_enabled = await SettingsService.get_bool(db, "vulnforge_enabled")
    if not vulnforge_enabled:
        return None

    vulnforge_url = await SettingsService.get(db, "vulnforge_url")
    if not vulnforge_url:
        logger.warning("VulnForge URL not configured")
        return None

    auth_type = await SettingsService.get(db, "vulnforge_auth_type", "none")
    api_key = await SettingsService.get(db, "vulnforge_api_key")

    # Auto-migrate stale basic_auth config
    if auth_type == "basic_auth":
        logger.warning(
            "VulnForge auth_type 'basic_auth' is no longer supported. "
            "VulnForge only accepts X-API-Key authentication. "
            "Falling back to auth_type='none'. Update your settings."
        )
        auth_type = "none"

    return VulnForgeClient(
        base_url=vulnforge_url,
        auth_type=auth_type or "none",
        api_key=api_key,
    )


class VulnForgeClient:
    """Client for querying VulnForge vulnerability data."""

    def __init__(
        self,
        base_url: str,
        auth_type: str = "none",
        api_key: str | None = None,
    ):
        """Initialize VulnForge client.

        Args:
            base_url: VulnForge API base URL (e.g., http://vulnforge:8787)
            auth_type: Authentication type (none or api_key)
            api_key: API key for X-API-Key header authentication
        """
        self.base_url = base_url.rstrip("/")
        self.auth_type = auth_type
        headers = {}

        if auth_type == "api_key" and api_key:
            headers["X-API-Key"] = api_key

        self.client = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensures client is closed."""
        await self.close()
        return False

    @staticmethod
    def _normalize_registry(registry: str | None) -> str:
        """Normalize registry identifiers to a canonical form."""
        if not registry:
            return "dockerhub"
        registry = registry.lower()
        alias_map = {
            "docker.io": "dockerhub",
            "index.docker.io": "dockerhub",
            "registry-1.docker.io": "dockerhub",
            "ghcr.io": "ghcr",
            "lscr.io": "lscr",
            "ghcr": "ghcr",
            "lscr": "lscr",
            "quay.io": "quay",
            "registry.k8s.io": "k8s",
            "gcr.io": "gcr",
        }
        return alias_map.get(registry, registry)

    @classmethod
    def _parse_image_repo(cls, repo: str) -> tuple[str, str, bool]:
        """Split an image repository into (registry, name, registry_explicit)."""
        if not repo:
            return "dockerhub", "", False

        parts = repo.split("/")
        registry = None
        name_parts = parts
        registry_explicit = False

        if parts and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
            registry = parts[0]
            name_parts = parts[1:]
            registry_explicit = True

        registry = cls._normalize_registry(registry)
        name = "/".join(name_parts).lower()

        if registry == "dockerhub":
            if name.startswith("library/"):
                name = name.split("/", 1)[1]
            if not name and parts:
                name = parts[-1]

        return registry, name, registry_explicit

    @classmethod
    def _container_matches(
        cls,
        container: dict,
        target_registry: str,
        target_name: str,
        target_tag: str,
        target_registry_explicit: bool,
    ) -> bool:
        """Determine if a VulnForge container matches the target image."""
        candidates: list[str] = []

        image_id = container.get("image_id")
        if image_id:
            candidates.append(image_id)

        image = container.get("image")
        image_tag = container.get("image_tag")
        if image and image_tag:
            candidates.append(f"{image}:{image_tag}")
        if image:
            candidates.append(image)

        for candidate in candidates:
            if not candidate:
                continue

            repo_part, sep, candidate_tag = candidate.rpartition(":")
            if sep == "":
                repo_part = candidate
                candidate_tag = image_tag or container.get("tag") or ""

            if candidate_tag != target_tag:
                continue

            candidate_registry, candidate_name, candidate_registry_explicit = cls._parse_image_repo(
                repo_part
            )

            if candidate_registry != target_registry:
                if candidate_registry_explicit and target_registry_explicit:
                    continue

            if candidate_name != target_name:
                continue

            return True

        return False

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    async def get_containers_by_image(
        self, image: str, tag: str | None = None
    ) -> list[dict] | None:
        """Find VulnForge containers matching an image name and optional tag.

        Tries the server-side ``/by-image`` endpoint first (O(1) indexed
        lookup).  Falls back to listing all containers and matching
        client-side when talking to an older VulnForge that lacks the
        endpoint.

        Args:
            image: Image repository name (e.g. "nginx", "ghcr.io/org/app").
            tag: Optional image tag filter. If None, returns all tags.

        Returns:
            List of matching container dicts, or None on connection error.
        """
        # --- fast path: server-side lookup ---
        try:
            params: dict[str, str] = {"image": image}
            if tag:
                params["tag"] = tag
            url = f"{self.base_url}/api/v1/containers/by-image"
            response = await self.client.get(url, params=params)

            if response.status_code == 200:
                return response.json()  # list[ContainerSchema]
            if response.status_code == 404:
                return []
            if response.status_code == 405:
                pass  # endpoint doesn't exist on old VulnForge; fall through
            else:
                response.raise_for_status()  # unexpected status → log & bail
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error looking up image: {e}")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"VulnForge /by-image returned {e.response.status_code}, falling back")
        except (ValueError, KeyError, AttributeError):
            pass  # malformed response → fall through to list-all

        # --- slow path: list all + client-side matching ---
        try:
            target_tag = tag or ""
            target_repo = image
            target_registry, target_name, target_registry_explicit = self._parse_image_repo(
                target_repo
            )

            url = f"{self.base_url}/api/v1/containers/"
            response = await self.client.get(url)
            response.raise_for_status()
            containers = response.json().get("containers", [])

            matches = []
            for container in containers:
                # When no tag filter, match any tag
                if not tag:
                    c_registry, c_name, c_explicit = self._parse_image_repo(
                        container.get("image", "")
                    )
                    if c_name == target_name and (
                        c_registry == target_registry
                        or not (c_explicit and target_registry_explicit)
                    ):
                        matches.append(container)
                elif self._container_matches(
                    container,
                    target_registry,
                    target_name,
                    target_tag,
                    target_registry_explicit,
                ):
                    matches.append(container)

            return matches

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error during fallback image lookup: {e}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"VulnForge API error during fallback image lookup: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid VulnForge response during fallback image lookup: {e}")
            return None

    async def get_image_vulnerabilities(
        self, image: str, tag: str, registry: str = "dockerhub"
    ) -> dict | None:
        """Get vulnerability data for a specific image tag.

        Args:
            image: Image name (e.g., "nginx" or "crowdsecurity/crowdsec")
            tag: Image tag (e.g., "latest", "v1.2.3")
            registry: Registry name (dockerhub, ghcr, etc.)

        Returns:
            Vulnerability data dict or None if not found
        """
        # Build full image reference
        if registry == "dockerhub":
            if "/" not in image:
                image_ref = f"library/{image}:{tag}"
            else:
                image_ref = f"{image}:{tag}"
        elif registry == "ghcr":
            image_ref = f"ghcr.io/{image}:{tag}"
        elif registry == "lscr":
            image_ref = f"lscr.io/{image}:{tag}"
        else:
            image_ref = f"{image}:{tag}"

        target_repo, target_tag = image_ref.rsplit(":", 1)
        target_registry, target_name, target_registry_explicit = self._parse_image_repo(target_repo)

        try:
            # Query VulnForge API for containers (VulnForge v1 API)
            url = f"{self.base_url}/api/v1/containers/"

            logger.info(f"Querying VulnForge containers for {image_ref}")
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()

            # Find container matching our image reference
            containers = data.get("containers", [])
            matching_container = None

            for container in containers:
                if self._container_matches(
                    container,
                    target_registry,
                    target_name,
                    target_tag,
                    target_registry_explicit,
                ):
                    matching_container = container
                    break

            if not matching_container:
                logger.warning(f"No vulnerability data found for {image_ref}")
                return None

            # Extract vulnerability data from container
            # VulnForge returns nested vulnerability_summary and last_scan objects
            # Both can be null if container has never been scanned
            vuln_summary = matching_container.get("vulnerability_summary") or {}
            last_scan = matching_container.get("last_scan") or {}

            # Fallback to top-level fields for backward compatibility (older VulnForge versions)
            if not vuln_summary:
                vuln_summary = {
                    "total": matching_container.get("total_vulns", 0),
                    "critical": matching_container.get("critical_count", 0),
                    "high": matching_container.get("high_count", 0),
                    "medium": matching_container.get("medium_count", 0),
                    "low": matching_container.get("low_count", 0),
                }

            # Get CVE list from latest scan if available
            cves = []
            if last_scan and last_scan.get("vulnerabilities"):
                cves = [v.get("cve_id") for v in last_scan["vulnerabilities"] if v.get("cve_id")]

            return {
                "image": image_ref,
                "scan_date": last_scan.get("finished_at") or last_scan.get("started_at"),
                "total_vulns": vuln_summary.get("total", 0),
                "critical": vuln_summary.get("critical", 0),
                "high": vuln_summary.get("high", 0),
                "medium": vuln_summary.get("medium", 0),
                "low": vuln_summary.get("low", 0),
                "cves": cves[:50],  # Limit to first 50 CVEs (VulnForge caps at 200)
                "risk_score": matching_container.get("risk_score", 0),
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info(f"Image {image_ref} not found in VulnForge")
                return None
            logger.error(f"VulnForge API error: {e}")
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid VulnForge response data: {e}")
            return None

    async def compare_vulnerabilities(
        self,
        current_image: str,
        current_tag: str,
        new_tag: str,
        registry: str = "dockerhub",
    ) -> dict | None:
        """Compare vulnerabilities between two image tags.

        Args:
            current_image: Image name
            current_tag: Current tag
            new_tag: New tag to compare
            registry: Registry name

        Returns:
            Comparison dict with delta information
        """
        # Get vulnerability data for both versions
        current_vulns = await self.get_image_vulnerabilities(current_image, current_tag, registry)
        new_vulns = await self.get_image_vulnerabilities(current_image, new_tag, registry)

        # If either is missing, can't compare
        if not current_vulns:
            logger.warning(f"No current vulnerability data for {current_image}:{current_tag}")
            return None

        if not new_vulns:
            logger.warning(f"No new vulnerability data for {current_image}:{new_tag}")
            return None

        # Calculate deltas
        total_delta = new_vulns["total_vulns"] - current_vulns["total_vulns"]
        critical_delta = new_vulns["critical"] - current_vulns["critical"]
        high_delta = new_vulns["high"] - current_vulns["high"]
        medium_delta = new_vulns["medium"] - current_vulns["medium"]
        low_delta = new_vulns["low"] - current_vulns["low"]

        # Find CVEs fixed and introduced
        current_cves = set(current_vulns.get("cves", []))
        new_cves = set(new_vulns.get("cves", []))

        cves_fixed = list(current_cves - new_cves)
        cves_introduced = list(new_cves - current_cves)

        # Determine if update is safe
        is_safe = total_delta <= 0  # Safe if vulns decrease or stay same
        is_improvement = total_delta < 0  # Improvement if vulns decrease

        # Generate summary
        if is_improvement:
            if len(cves_fixed) > 0:
                summary = f"Fixes {len(cves_fixed)} CVE(s)"
            else:
                summary = f"Reduces vulnerabilities by {abs(total_delta)}"
        elif total_delta == 0:
            summary = "No change in vulnerability count"
        else:
            summary = f"Introduces {total_delta} new vulnerability(s)"

        return {
            "current": current_vulns,
            "new": new_vulns,
            "delta": {
                "total": total_delta,
                "critical": critical_delta,
                "high": high_delta,
                "medium": medium_delta,
                "low": low_delta,
            },
            "cves_fixed": cves_fixed,
            "cves_introduced": cves_introduced,
            "is_safe": is_safe,
            "is_improvement": is_improvement,
            "summary": summary,
            "recommendation": self._get_recommendation(
                total_delta, critical_delta, high_delta, cves_fixed
            ),
        }

    def _get_recommendation(
        self,
        total_delta: int,
        critical_delta: int,
        high_delta: int,
        cves_fixed: list[str],
    ) -> str:
        """Generate update recommendation based on vulnerability deltas.

        Args:
            total_delta: Change in total vulnerabilities
            critical_delta: Change in critical vulnerabilities
            high_delta: Change in high vulnerabilities
            cves_fixed: List of CVE IDs fixed

        Returns:
            Recommendation string
        """
        # Critical vulnerabilities introduced
        if critical_delta > 0:
            return "Not recommended - introduces critical vulnerabilities"

        # Critical vulnerabilities fixed
        if critical_delta < 0:
            return "Highly recommended - fixes critical vulnerabilities"

        # High vulnerabilities introduced
        if high_delta > 0 and total_delta > 0:
            return "Review required - introduces high severity vulnerabilities"

        # CVEs fixed
        if len(cves_fixed) > 0:
            return f"Recommended - fixes {len(cves_fixed)} CVE(s)"

        # Vulnerability reduction
        if total_delta < 0:
            return "Recommended - reduces overall vulnerabilities"

        # No change
        if total_delta == 0:
            return "Optional - no security impact"

        # Vulnerabilities introduced
        if total_delta > 0:
            return "Not recommended - introduces new vulnerabilities"

        return "Review required"

    async def trigger_container_discovery(self) -> dict | None:
        """Trigger VulnForge container discovery.

        Asks VulnForge to re-scan the Docker daemon for new/removed
        containers.  Used when a container has been recreated and VulnForge
        may not know about it yet.

        Returns:
            Discovery result dict (total, discovered, removed, message),
            or None on error.
        """
        try:
            url = f"{self.base_url}/api/v1/containers/discover"
            logger.info("Triggering VulnForge container discovery")
            response = await self.client.post(url)
            response.raise_for_status()
            data = response.json()
            discovered = data.get("discovered", [])
            if discovered:
                logger.info(f"VulnForge discovered new containers: {discovered}")
            return data
        except httpx.HTTPStatusError as e:
            logger.warning(f"VulnForge discovery returned {e.response.status_code}: {e}")
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error during discovery: {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response from VulnForge discovery: {e}")
            return None

    async def trigger_scan(self, container_id: int) -> dict | None:
        """Trigger a vulnerability scan for a container in VulnForge.

        Args:
            container_id: VulnForge container ID to scan

        Returns:
            Response dict with job_ids and queue info, or None on failure
        """
        try:
            url = f"{self.base_url}/api/v1/scans/scan"
            payload = {"container_ids": [container_id]}

            logger.info(f"Triggering VulnForge scan for container ID {container_id}")
            response = await self.client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()
            logger.info(
                f"Scan triggered for container ID {container_id}, job_ids={data.get('job_ids', [])}"
            )
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"VulnForge API error triggering scan: {e}")
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error triggering scan: {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid data triggering scan: {e}")
            return None

    async def get_container_id_by_name(self, container_name: str) -> int | None:
        """Find VulnForge container ID by container name.

        Tries O(1) by-name endpoint first, falls back to list-all for
        backward compatibility with older VulnForge versions.

        Args:
            container_name: Docker container name (e.g., "nginx", "sonarr")

        Returns:
            VulnForge container ID or None if not found
        """
        # Try direct by-name lookup first (O(1))
        try:
            url = f"{self.base_url}/api/v1/containers/by-name/{container_name}"
            response = await self.client.get(url)
            if response.status_code == 200:
                data = response.json()
                container_id = data.get("id")
                if container_id:
                    return container_id
            elif response.status_code == 404:
                logger.warning(f"Container '{container_name}' not found in VulnForge")
                return None
            # Other errors: fall through to list-all fallback
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error looking up container: {e}")
            return None
        except (ValueError, KeyError, AttributeError):
            pass  # Fall through to list-all

        # Fallback: list all containers and search (O(N))
        try:
            url = f"{self.base_url}/api/v1/containers/"
            response = await self.client.get(url)
            response.raise_for_status()
            containers = response.json().get("containers", [])

            for c in containers:
                if c.get("name") == container_name:
                    return c.get("id")

            logger.warning(f"Container '{container_name}' not found in VulnForge")
            return None

        except httpx.HTTPStatusError as e:
            logger.error(f"VulnForge API error looking up container: {e}")
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error looking up container: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid VulnForge response looking up container: {e}")
            return None

    async def trigger_scan_by_name(self, container_name: str) -> dict | None:
        """Trigger scan for container by name (TideWatch container name).

        This is a convenience method that looks up the VulnForge container ID
        by name and then triggers a scan for it.

        Args:
            container_name: Docker container name

        Returns:
            Response dict with job_ids, or None if not found or failed
        """
        container_id = await self.get_container_id_by_name(container_name)
        if not container_id:
            logger.warning(
                f"Cannot trigger scan: container '{container_name}' not found in VulnForge"
            )
            return None
        return await self.trigger_scan(container_id)

    async def get_scan_job_status(self, job_id: int) -> dict | None:
        """Poll VulnForge for scan job status.

        Args:
            job_id: ScanJob ID returned from trigger_scan

        Returns:
            Job status dict (id, status, scan_id, etc.) or None on error
        """
        try:
            url = f"{self.base_url}/api/v1/scans/jobs/{job_id}"
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Scan job {job_id} not found in VulnForge")
                return None
            logger.error(f"VulnForge API error getting scan job status: {e}")
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error getting scan job status: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid VulnForge response for scan job status: {e}")
            return None

    async def get_cve_delta(
        self,
        container_name: str | None = None,
        since_hours: int = 24,
        scan_id: int | None = None,
    ) -> dict | None:
        """Get CVE delta from VulnForge's cve-delta endpoint.

        This queries VulnForge for CVEs fixed and introduced in recent scans.
        Useful for displaying "CVEs Resolved" after container updates.

        Args:
            container_name: Optional filter for specific container
            since_hours: Number of hours to look back (default 24)
            scan_id: Optional specific scan ID for deterministic retrieval

        Returns:
            Dict with CVE delta information or None on error
        """
        try:
            url = f"{self.base_url}/api/v1/scans/cve-delta"
            params: dict[str, Any] = {"since_hours": since_hours}
            if container_name:
                params["container_name"] = container_name
            if scan_id:
                params["scan_id"] = scan_id

            logger.info(f"Querying VulnForge CVE delta: {params}")
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"VulnForge API error getting CVE delta: {e}")
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error getting CVE delta: {e}")
            return None
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Invalid VulnForge response for CVE delta: {e}")
            return None
