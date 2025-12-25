"""VulnForge API client for vulnerability data."""

import logging
from typing import Optional, Dict, List
import base64

import httpx

logger = logging.getLogger(__name__)


class VulnForgeClient:
    """Client for querying VulnForge vulnerability data."""

    def __init__(
        self,
        base_url: str,
        auth_type: str = "none",
        api_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize VulnForge client.

        Args:
            base_url: VulnForge API base URL (e.g., http://vulnforge:8787)
            auth_type: Authentication type (none, api_key, basic_auth)
            api_key: API key for Bearer token authentication
            username: Username for basic authentication
            password: Password for basic authentication
        """
        self.base_url = base_url.rstrip("/")
        self.auth_type = auth_type
        headers = {}

        # Configure authentication based on type
        if auth_type == "api_key" and api_key:
            # VulnForge uses standard Bearer token authentication
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_type == "basic_auth" and username and password:
            # HTTP Basic authentication
            credentials = f"{username}:{password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        # auth_type == "none" requires no headers

        self.client = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensures client is closed."""
        await self.close()
        return False

    @staticmethod
    def _normalize_registry(registry: Optional[str]) -> str:
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
        container: Dict,
        target_registry: str,
        target_name: str,
        target_tag: str,
        target_registry_explicit: bool,
    ) -> bool:
        """Determine if a VulnForge container matches the target image."""
        candidates: List[str] = []

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

            candidate_registry, candidate_name, candidate_registry_explicit = (
                cls._parse_image_repo(repo_part)
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

    async def get_image_vulnerabilities(
        self, image: str, tag: str, registry: str = "dockerhub"
    ) -> Optional[Dict]:
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
        target_registry, target_name, target_registry_explicit = self._parse_image_repo(
            target_repo
        )

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
                cves = [
                    v.get("cve_id")
                    for v in last_scan["vulnerabilities"]
                    if v.get("cve_id")
                ]

            return {
                "image": image_ref,
                "scan_date": last_scan.get("finished_at")
                or last_scan.get("started_at"),
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
    ) -> Optional[Dict]:
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
        current_vulns = await self.get_image_vulnerabilities(
            current_image, current_tag, registry
        )
        new_vulns = await self.get_image_vulnerabilities(
            current_image, new_tag, registry
        )

        # If either is missing, can't compare
        if not current_vulns:
            logger.warning(
                f"No current vulnerability data for {current_image}:{current_tag}"
            )
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
        cves_fixed: List[str],
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

    async def trigger_scan(self, container_id: int) -> bool:
        """Trigger a vulnerability scan for a container in VulnForge.

        Args:
            container_id: VulnForge container ID to scan

        Returns:
            True if scan triggered successfully
        """
        try:
            url = f"{self.base_url}/api/v1/scans/scan"
            payload = {"container_ids": [container_id]}

            logger.info(f"Triggering VulnForge scan for container ID {container_id}")
            response = await self.client.post(url, json=payload)
            response.raise_for_status()

            logger.info(f"Scan triggered for container ID {container_id}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"VulnForge API error triggering scan: {e}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"VulnForge connection error triggering scan: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid data triggering scan: {e}")
            return False

    async def get_container_id_by_name(self, container_name: str) -> Optional[int]:
        """Find VulnForge container ID by container name.

        Args:
            container_name: Docker container name (e.g., "nginx", "sonarr")

        Returns:
            VulnForge container ID or None if not found
        """
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

    async def trigger_scan_by_name(self, container_name: str) -> bool:
        """Trigger scan for container by name (TideWatch container name).

        This is a convenience method that looks up the VulnForge container ID
        by name and then triggers a scan for it.

        Args:
            container_name: Docker container name

        Returns:
            True if scan triggered successfully
        """
        container_id = await self.get_container_id_by_name(container_name)
        if not container_id:
            logger.warning(
                f"Cannot trigger scan: container '{container_name}' not found in VulnForge"
            )
            return False
        return await self.trigger_scan(container_id)

    async def get_cve_delta(
        self, container_name: Optional[str] = None, since_hours: int = 24
    ) -> Optional[Dict]:
        """Get CVE delta from VulnForge's cve-delta endpoint.

        This queries VulnForge for CVEs fixed and introduced in recent scans.
        Useful for displaying "CVEs Resolved" after container updates.

        Args:
            container_name: Optional filter for specific container
            since_hours: Number of hours to look back (default 24)

        Returns:
            Dict with CVE delta information or None on error
        """
        try:
            url = f"{self.base_url}/api/v1/scans/cve-delta"
            params: Dict[str, any] = {"since_hours": since_hours}
            if container_name:
                params["container_name"] = container_name

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
