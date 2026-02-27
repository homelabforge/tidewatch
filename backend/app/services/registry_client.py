"""Registry clients for checking Docker image updates."""

import logging
import platform
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

import httpx
from packaging.version import InvalidVersion, Version

from app.utils.retry import async_retry

logger = logging.getLogger(__name__)


class RegistryCheckError(Exception):
    """Raised when a registry check fails due to rate limiting or connection issues.

    This exception indicates a transient failure that should NOT clear existing
    pending updates. The caller should preserve any existing update records
    since we couldn't verify their status.
    """

    def __init__(self, message: str, status_code: int | None = None):
        """Initialize the exception.

        Args:
            message: Error description
            status_code: HTTP status code if applicable (e.g., 429 for rate limit)
        """
        super().__init__(message)
        self.status_code = status_code
        self.is_rate_limit = status_code == 429


# Non-PEP 440 prerelease indicators that packaging.Version won't detect
# These are common in Docker image tags but not standard Python versioning
NON_PEP440_PRERELEASE_INDICATORS = [
    "nightly",
    "develop",
    "dev",
    "master",
    "main",
    "preview",
    "unstable",
    "snapshot",
    "canary",
    "edge",
    "test",
    "testing",
    "experimental",
    "exp",
    "pr-",
    "pull-",
    "branch-",
    "feat-",
    "feature-",
    "fix-",
    "hotfix-",
]


def is_prerelease_tag(tag: str) -> bool:
    """Detect if a Docker image tag represents a prerelease version.

    Uses a hybrid approach:
    1. Try parsing with packaging.Version and check is_prerelease (catches PEP 440: alpha, beta, rc, dev, etc.)
    2. Fall back to pattern matching for non-standard indicators (nightly, unstable, etc.)

    Args:
        tag: Docker image tag to check

    Returns:
        True if the tag appears to be a prerelease version
    """
    tag_lower = tag.lower().lstrip("v")

    # First, try PEP 440 detection via packaging library
    try:
        # Handle build metadata
        version_str = tag_lower.split("+")[0] if "+" in tag_lower else tag_lower
        parsed = Version(version_str)
        if parsed.is_prerelease or parsed.is_devrelease:
            return True
    except InvalidVersion:
        # If it doesn't parse as a valid version, check if the base parses
        # e.g., "4.6.0-unstable" -> try "4.6.0" then check suffix
        for sep in ("-", "_"):
            if sep in tag_lower:
                parts = tag_lower.split(sep, 1)
                try:
                    Version(parts[0])
                    # Base is valid, check if suffix indicates prerelease
                    suffix = parts[1].lower()
                    # Check non-PEP 440 indicators in suffix
                    if any(indicator in suffix for indicator in NON_PEP440_PRERELEASE_INDICATORS):
                        return True
                except InvalidVersion:
                    pass

    # Second, check for non-PEP 440 patterns in the full tag
    # Use word boundary matching to avoid false positives (e.g., 'latest' shouldn't match 'test')
    for indicator in NON_PEP440_PRERELEASE_INDICATORS:
        # Handle prefix patterns (e.g., 'pr-', 'feat-') - check if tag starts with indicator
        if indicator.endswith("-"):
            # For patterns like 'pr-', check if tag starts with 'pr-' (case-insensitive)
            if tag_lower.startswith(indicator):
                return True
            # Also check if any segment after splitting starts with the prefix
            # e.g., '1.0-pr-123' should match 'pr-'
            segments = re.split(r"[-_.]", tag_lower)
            if any(seg.startswith(indicator) for seg in segments):
                return True
        else:
            # For exact word patterns (e.g., 'nightly', 'test'), check exact segment match
            segments = re.split(r"[-_.]", tag_lower)
            if indicator in segments:
                return True

    return False


def extract_tag_pattern(tag: str) -> str:
    """Extract a structural pattern from a Docker tag for comparison.

    Converts numeric sequences to 'N' while preserving literal parts.
    This allows matching tags with the same structure but different versions.

    Examples:
        '4.0.16.2944-ls300' -> 'N.N.N.N-lsN'
        '5.14-version-2.0.0.5344' -> 'N.N-version-N.N.N.N'
        'latest' -> 'latest'
        'v1.2.3' -> 'vN.N.N'
        '3.12-alpine' -> 'N.N-alpine'

    Args:
        tag: Docker image tag

    Returns:
        Pattern string with numeric parts replaced by 'N'
    """
    # Replace sequences of digits with 'N'
    pattern = re.sub(r"\d+", "N", tag)
    return pattern


def tags_have_matching_pattern(current_tag: str, candidate_tag: str) -> bool:
    """Check if two tags have the same structural pattern.

    Args:
        current_tag: The current tag in use
        candidate_tag: A candidate tag being considered for update

    Returns:
        True if patterns match, False otherwise
    """
    return extract_tag_pattern(current_tag) == extract_tag_pattern(candidate_tag)


def is_non_semver_tag(tag: str) -> bool:
    """Check if a tag requires digest-based tracking (non-semantic version).

    Non-semver tags like 'latest', 'lts', 'stable', 'alpine', 'edge' cannot
    be compared using version logic and must use digest-based change detection.

    Args:
        tag: Tag to check

    Returns:
        True if tag cannot be parsed as a semantic version
    """
    version = tag.lstrip("v")
    if version == "latest":
        return True

    if "+" in version:
        version = version.split("+", 1)[0]

    try:
        Version(version)
        return False
    except InvalidVersion:
        for sep in ("-", "_"):
            if sep in version:
                base = version.split(sep, 1)[0]
                try:
                    Version(base)
                    return False
                except InvalidVersion:
                    continue
        return True


# Simple in-memory cache for registry tags with TTL
class TagCache:
    """Thread-safe in-memory cache for registry tags with TTL."""

    def __init__(self, ttl_minutes: int = 15) -> None:
        """Initialize cache with TTL.

        Args:
            ttl_minutes: Time-to-live in minutes (default: 15)
        """
        self._cache: dict[str, dict] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    def get(self, key: str) -> list[str] | None:
        """Get cached tags if not expired.

        Args:
            key: Cache key (e.g., "dockerhub:nginx")

        Returns:
            List of tags or None if expired/missing
        """
        if key not in self._cache:
            return None

        entry = self._cache[key]
        if datetime.now(UTC) > entry["expires_at"]:
            # Expired, remove it
            del self._cache[key]
            return None

        return entry["tags"]

    def set(self, key: str, tags: list[str]) -> None:
        """Store tags in cache with TTL.

        Args:
            key: Cache key
            tags: List of tags to cache
        """
        self._cache[key] = {
            "tags": tags,
            "expires_at": datetime.now(UTC) + self._ttl,
        }

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        now = datetime.now(UTC)
        expired_keys = [key for key, entry in self._cache.items() if now > entry["expires_at"]]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)


# Global tag cache instance (15 minute TTL)
_tag_cache = TagCache(ttl_minutes=15)


ARCH_SUFFIX_PATTERNS = tuple(
    sorted(
        [
            "amd64",
            "x86_64",
            "amd64v2",
            "arm64",
            "arm64v8",
            "aarch64",
            "arm32v7",
            "arm32v6",
            "armv7l",
            "armv7",
            "armhf",
            "armv6",
            "arm",
            "386",
            "i386",
            "ppc64le",
            "s390x",
            "riscv64",
        ],
        key=len,
        reverse=True,
    )
)


def canonical_arch_suffix(suffix: str | None) -> str | None:
    """Normalize architecture suffix aliases to a canonical form."""
    if suffix is None:
        return None

    mapping = {
        "x86_64": "amd64",
        "amd64v2": "amd64",
        "arm64v8": "arm64",
        "aarch64": "arm64",
        "arm32v7": "arm",
        "arm32v6": "armv6",
        "armv7l": "arm",
        "armv7": "arm",
        "armhf": "arm",
        "i386": "386",
    }
    return mapping.get(suffix, suffix)


HOST_ARCH_CANONICAL = canonical_arch_suffix(platform.machine().lower())


class RegistryClient(ABC):
    """Base class for registry clients."""

    # Whether get_latest_tag() internally calls get_all_tags() and benefits
    # from TagCache being pre-populated.  True for GHCR/LSCR/GCR/Quay;
    # overridden to False for Docker Hub whose get_latest_tag uses a separate
    # optimized paginated fetch (_get_semver_update) that does not use TagCache.
    uses_tag_cache_for_latest: bool = True

    def __init__(self, username: str | None = None, token: str | None = None) -> None:
        """Initialize registry client.

        Args:
            username: Optional username/token for authentication
            token: Optional password/token for authentication
        """
        headers = {}
        auth = None

        # Set up authentication if credentials provided
        if username and token:
            auth = (username, token)
        elif token:  # Token-only auth (GitHub PAT, etc.)
            headers["Authorization"] = f"Bearer {token}"

        self.client = httpx.AsyncClient(timeout=30.0, headers=headers, auth=auth if auth else None)
        self._registry_name = self.__class__.__name__.replace("Client", "").lower()

    def _get_cache_key(self, image: str) -> str:
        """Generate cache key for image.

        Args:
            image: Image name

        Returns:
            Cache key string
        """
        return f"{self._registry_name}:{image}"

    async def __aenter__(self) -> "RegistryClient":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self, _exc_type: type | None, _exc_val: BaseException | None, _exc_tb: object | None
    ) -> bool:
        """Async context manager exit - ensures client is closed."""
        await self.close()
        return False

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    @async_retry(
        max_attempts=3,
        backoff_base=1.0,
        backoff_max=10.0,
        exceptions=(httpx.HTTPError, httpx.TimeoutException, httpx.ConnectError),
    )
    async def _get_with_retry(self, url: str, **kwargs) -> httpx.Response:
        """Make HTTP GET request with automatic retry on transient failures.

        Args:
            url: URL to fetch
            **kwargs: Additional arguments to pass to httpx.get()

        Returns:
            HTTP response

        Raises:
            httpx.HTTPError: If all retry attempts fail
        """
        response = await self.client.get(url, **kwargs)
        response.raise_for_status()
        return response

    @abstractmethod
    async def get_latest_tag(
        self,
        image: str,
        current_tag: str,
        scope: str = "patch",
        current_digest: str | None = None,
        include_prereleases: bool = False,
    ) -> str | None:
        """Get latest tag for an image.

        Args:
            image: Image name (e.g., "nginx" or "linuxserver/plex")
            current_tag: Current tag (e.g., "1.2.3")
            scope: Update scope (patch, minor, major)
            current_digest: Current digest (for latest tag tracking)
            include_prereleases: Include nightly, dev, alpha, beta, rc tags

        Returns:
            Latest tag or None
        """
        pass

    @abstractmethod
    async def get_all_tags(self, image: str) -> list[str]:
        """Get all available tags for an image.

        Args:
            image: Image name

        Returns:
            List of tags
        """
        pass

    @abstractmethod
    async def get_tag_metadata(self, image: str, tag: str) -> dict | None:
        """Get metadata for a specific tag.

        Args:
            image: Image name
            tag: Tag name

        Returns:
            Metadata dict with digest, created_at, etc.
        """
        pass

    def _compare_versions(self, current: str, candidate: str, scope: str) -> bool:
        """Compare semantic versions based on scope.

        Args:
            current: Current version (e.g., "1.2.3")
            candidate: Candidate version (e.g., "1.2.4")
            scope: Update scope (patch, minor, major)

        Returns:
            True if candidate is a valid update
        """
        # Filter out Windows images on Linux systems
        if self._is_windows_image(candidate):
            logger.debug(
                "Skipping Windows image tag %s for %s",
                candidate,
                current,
            )
            return False

        if self._has_arch_mismatch(current, candidate):
            logger.debug(
                "Skipping candidate tag %s for %s due to architecture mismatch",
                candidate,
                current,
            )
            return False

        # Try to parse as semantic version
        normalized_current = self._normalize_version(current)
        normalized_candidate = self._normalize_version(candidate)

        if not normalized_current or not normalized_candidate:
            # Cannot compare semantically — don't fall back to lexicographic
            # comparison because e.g. "1.9.9" > "1.10.0" is True lexicographically
            return False

        curr_major, curr_minor, curr_patch, curr_extra = normalized_current
        cand_major, cand_minor, cand_patch, cand_extra = normalized_candidate

        if (cand_major, cand_minor, cand_patch, cand_extra) <= (
            curr_major,
            curr_minor,
            curr_patch,
            curr_extra,
        ):
            return False

        # Check scope
        if scope == "patch":
            # Only allow patch updates (same major.minor)
            return cand_major == curr_major and cand_minor == curr_minor
        elif scope == "minor":
            # Allow minor and patch updates (same major)
            return cand_major == curr_major
        else:  # major
            # Allow any newer version
            return True

    def _normalize_version(self, version: str) -> tuple[int, int, int, tuple] | None:
        """Normalize version strings for comparison."""
        version = version.lstrip("v")
        if version == "latest":
            return None

        if "+" in version:
            version = version.split("+", 1)[0]

        try:
            parsed = Version(version)
        except InvalidVersion:
            for sep in ("-", "_"):
                if sep in version:
                    base = version.split(sep, 1)[0]
                    try:
                        parsed = Version(base)
                        break
                    except InvalidVersion:
                        continue
            else:
                return None
        return (
            parsed.release[0] if len(parsed.release) > 0 else 0,
            parsed.release[1] if len(parsed.release) > 1 else 0,
            parsed.release[2] if len(parsed.release) > 2 else 0,
            tuple(parsed.pre or ()),
        )

    def _parse_semver(self, version: str) -> tuple[int, int, int, tuple] | None:
        """Backward-compatible helper for existing version-parsing calls."""
        return self._normalize_version(version)

    def _is_better_version(self, candidate: str, current_best: str) -> bool:
        """Compare two version tags using semantic version ordering.

        Uses packaging.Version for comparison instead of lexicographic
        string comparison, which would incorrectly rank '1.9.9' above
        '1.10.0'. Also correctly handles prerelease ordering (2.0.0 > 2.0.0rc1).

        Falls back to string comparison only when neither version can be parsed.

        Args:
            candidate: Version tag to evaluate
            current_best: Current best version tag

        Returns:
            True if candidate is a newer version than current_best
        """
        candidate_parsed = self._try_parse_version(candidate)
        best_parsed = self._try_parse_version(current_best)

        if candidate_parsed is not None and best_parsed is not None:
            return candidate_parsed > best_parsed
        # If only one parses, prefer the parseable one
        if candidate_parsed is not None and best_parsed is None:
            return True
        if candidate_parsed is None and best_parsed is not None:
            return False
        # Neither parses — fall back to string comparison
        return candidate > current_best

    @staticmethod
    def _try_parse_version(tag: str) -> Version | None:
        """Try to parse a tag as a PEP 440 version.

        Args:
            tag: Version string (may have 'v' prefix or build metadata)

        Returns:
            Version object or None if unparseable
        """
        version = tag.lstrip("v")
        if "+" in version:
            version = version.split("+", 1)[0]
        try:
            return Version(version)
        except InvalidVersion:
            for sep in ("-", "_"):
                if sep in version:
                    base = version.split(sep, 1)[0]
                    try:
                        return Version(base)
                    except InvalidVersion:
                        continue
            return None

    @staticmethod
    def _is_linuxserver_image(image: str) -> bool:
        """Return True if the image is from the LinuxServer project.

        Matches 'linuxserver' as a path segment in any registry format:
          - 'linuxserver/sonarr'          (DockerHub)
          - 'ghcr.io/linuxserver/sonarr'  (GHCR)
          - 'lscr.io/linuxserver/sonarr'  (LSCR via generic client)

        Args:
            image: Docker image reference string.

        Returns:
            True if 'linuxserver' is a segment in the image path.
        """
        return "linuxserver" in image.lower().split("/")

    @staticmethod
    def _extract_variant_suffix(tag: str, normalize_ls: bool = False) -> str | None:
        """Extract semantic variant suffix for cross-version matching.

        Returns the portion of a tag after the first hyphen, lowercased. When
        normalize_ls is True (LinuxServer images only), suffixes matching the
        LinuxServer build-counter pattern (ls<N> or <hash>-ls<N>) are normalized
        to the stable token 'ls' so counter churn does not block updates.

        Non-LinuxServer suffixes — including digit-bearing ones like 'alpine3.20'
        or 'cuda12' — are always returned verbatim to preserve strict track
        matching.

        Args:
            tag: Docker image tag string.
            normalize_ls: If True, apply LinuxServer build-counter normalization.

        Returns:
            Normalized suffix string, or None if no hyphen-separated suffix exists.

        Examples (normalize_ls=False):
            'v1.13.4-ls131'            -> 'ls131'      (raw, strict)
            '3.12-alpine3.20'          -> 'alpine3.20'  (raw, strict)
            '1.2.3'                    -> None

        Examples (normalize_ls=True):
            'v1.13.4-ls131'                -> 'ls'       (normalized)
            'v1.13.10-ls140'               -> 'ls'       (normalized, same)
            '1.42.2.10156-f737b826c-ls284' -> 'ls'       (composite normalized)
            '3.12-alpine'                  -> 'alpine'   (no ls counter, unchanged)
            '3.12-alpine3.20'              -> 'alpine3.20' (no ls counter, unchanged)
        """
        tag_without_v = tag.lstrip("vV")
        if "-" not in tag_without_v:
            return None
        suffix = tag_without_v.split("-", 1)[1].lower()
        if normalize_ls and re.search(r"(?:^|-)ls\d+$", suffix):
            return "ls"
        return suffix

    def _is_non_semver_tag(self, tag: str) -> bool:
        """Check if tag requires digest tracking (non-semantic version).

        Non-semver tags like 'latest', 'lts', 'stable', 'alpine', 'edge' cannot be
        compared using version logic and must use digest-based change detection.

        Args:
            tag: Tag to check

        Returns:
            True if tag cannot be parsed as semantic version
        """
        return self._parse_semver(tag) is None

    def _extract_arch_suffix(self, tag: str) -> str | None:
        """Extract canonical architecture suffix from a tag if present."""
        lower_tag = tag.lower()
        for suffix in ARCH_SUFFIX_PATTERNS:
            if lower_tag.endswith(f"-{suffix}"):
                return canonical_arch_suffix(suffix)
        return None

    def _has_arch_mismatch(self, current: str, candidate: str) -> bool:
        """Determine whether candidate tag targets an incompatible architecture."""
        current_suffix = self._extract_arch_suffix(current)
        candidate_suffix = self._extract_arch_suffix(candidate)

        if current_suffix and candidate_suffix:
            return current_suffix != candidate_suffix

        if current_suffix and not candidate_suffix:
            # User pinned to an architecture-specific tag; avoid switching styles.
            return True

        if candidate_suffix and not current_suffix:
            # Allow architecture-specific tags only when they match the host arch.
            if HOST_ARCH_CANONICAL:
                return candidate_suffix != canonical_arch_suffix(HOST_ARCH_CANONICAL)
            return True

        return False

    def _is_windows_image(self, tag: str) -> bool:
        """Check if a tag is for a Windows image."""
        lower_tag = tag.lower()
        windows_indicators = [
            "windowsservercore",
            "nanoserver",
            "ltsc",
            "windowsserver",
            "-windows",
        ]
        return any(indicator in lower_tag for indicator in windows_indicators)

    async def get_latest_major_tag(
        self, image: str, current_tag: str, include_prereleases: bool = False
    ) -> str | None:
        """Get latest major version regardless of container scope.

        This method ALWAYS checks with scope='major' to find the absolute
        latest version, even if container scope is set to patch/minor.

        Args:
            image: Image name
            current_tag: Current tag
            include_prereleases: Include pre-release tags

        Returns:
            Latest major version or None
        """
        # For non-semver tags, return None (no concept of major version)
        if self._is_non_semver_tag(current_tag):
            return None

        # Delegate to registry-specific implementation
        # This uses get_latest_tag with scope='major'
        return await self.get_latest_tag(
            image,
            current_tag,
            scope="major",  # Always major scope
            current_digest=None,  # Not needed for semver tags
            include_prereleases=include_prereleases,
        )


class DockerHubClient(RegistryClient):
    """Docker Hub registry client."""

    BASE_URL = "https://hub.docker.com/v2"
    uses_tag_cache_for_latest: bool = False

    async def get_all_tags(self, image: str) -> list[str]:
        """Get all tags from Docker Hub with caching.

        Args:
            image: Image name (e.g., "nginx" or "library/nginx")

        Returns:
            List of tag names
        """
        # Docker Hub uses "library/" for official images
        if "/" not in image:
            image = f"library/{image}"

        # Check cache first
        cache_key = self._get_cache_key(image)
        cached_tags = _tag_cache.get(cache_key)
        if cached_tags is not None:
            logger.debug(f"Cache hit for {image} ({len(cached_tags)} tags)")
            return cached_tags

        url = f"{self.BASE_URL}/repositories/{image}/tags"
        tags = []

        try:
            while url:
                response = await self.client.get(url)
                response.raise_for_status()
                data = response.json()

                for tag_data in data.get("results", []):
                    tags.append(tag_data["name"])

                # Check for pagination
                url = data.get("next")

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching Docker Hub tags for {image}: {e.response.status_code}"
            )
            raise RegistryCheckError(
                f"HTTP error fetching Docker Hub tags for {image}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching Docker Hub tags for {image}: {e}")
            raise RegistryCheckError(
                f"Connection error fetching Docker Hub tags for {image}: {e}"
            ) from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching Docker Hub tags for {image}: {e}")
            raise RegistryCheckError(f"Timeout fetching Docker Hub tags for {image}: {e}") from e
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response data fetching Docker Hub tags for {image}: {e}")
            return []

        # Cache the results
        _tag_cache.set(cache_key, tags)
        logger.debug(f"Cached {len(tags)} tags for {image}")

        return tags

    async def get_latest_tag(
        self,
        image: str,
        current_tag: str,
        scope: str = "patch",
        current_digest: str | None = None,
        include_prereleases: bool = False,
    ) -> str | None:
        """Get latest tag from Docker Hub.

        Optimized approach:
        - For 'latest' tag: Check digest only (1 API call)
        - For semver tags: Fetch with page_size=100 and stop early

        Args:
            image: Image name
            current_tag: Current tag
            scope: Update scope (patch, minor, major)
            current_digest: Current digest (for latest tag tracking)
            include_prereleases: Include nightly, dev, alpha, beta, rc tags

        Returns:
            New tag if update available, None otherwise
        """
        # Check if tag is non-semver (needs digest tracking)
        if self._is_non_semver_tag(current_tag):
            result = await self._check_digest_change(image, current_tag, current_digest)
            if result and result.get("changed"):
                return current_tag  # Return the tag name if changed
            return None  # No update

        # For semantic versions, use optimized fetching
        return await self._get_semver_update(image, current_tag, scope, include_prereleases)

    async def _check_digest_change(
        self, image: str, current_tag: str, current_digest: str | None = None
    ) -> dict | None:
        """Check if non-semver tag has new digest.

        Works for any non-semver tag including 'latest', 'lts', 'stable', 'alpine', etc.

        Args:
            image: Image name
            current_tag: Current tag (any non-semver tag)
            current_digest: Stored digest from database (if available)

        Returns:
            Dict with 'tag' and 'digest' if changed, None if same or error
        """
        try:
            # Fetch current digest from registry
            metadata = await self.get_tag_metadata(image, current_tag)
            if not metadata:
                logger.warning(f"Failed to fetch metadata for {image}:{current_tag}")
                return None

            new_digest = metadata.get("digest")
            if not new_digest:
                logger.warning(f"No digest in metadata for {image}:{current_tag}")
                return None

            # If we have a stored digest, compare them
            if current_digest:
                if current_digest == new_digest:
                    logger.debug(f"Digest unchanged for {image}:{current_tag} ({new_digest})")
                    return None  # No change
                else:
                    logger.info(
                        f"Digest changed for {image}:{current_tag}: {current_digest} -> {new_digest}"
                    )
                    return {"tag": current_tag, "digest": new_digest, "changed": True}
            else:
                # No stored digest - this is the first check, store it
                logger.info(f"No previous digest for {image}:{current_tag}, storing: {new_digest}")
                return {
                    "tag": current_tag,
                    "digest": new_digest,
                    "changed": False,  # Not a change, just initial state
                }

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error checking digest for {image}:{current_tag}: {e.response.status_code}"
            )
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error checking digest for {image}:{current_tag}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout checking digest for {image}:{current_tag}: {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid metadata checking digest for {image}:{current_tag}: {e}")
            return None

    async def _get_semver_update(
        self,
        image: str,
        current_tag: str,
        scope: str,
        include_prereleases: bool = False,
    ) -> str | None:
        """Get semantic version update with optimized API calls.

        Fetches tags in larger pages and stops early when possible.
        """
        if "/" not in image:
            image = f"library/{image}"

        url = f"{self.BASE_URL}/repositories/{image}/tags?page_size=100"
        best_tag = None
        current_version = self._parse_semver(current_tag)
        normalize_ls = self._is_linuxserver_image(image)
        current_variant = self._extract_variant_suffix(current_tag, normalize_ls=normalize_ls)

        try:
            # Fetch up to 500 tags (5 pages) max
            for _page in range(5):
                response = await self.client.get(url)
                response.raise_for_status()
                data = response.json()

                # Process this page's tags
                for tag_data in data.get("results", []):
                    tag_name = tag_data["name"]

                    # Skip "latest" tag explicitly (not a version)
                    if tag_name.lower() == "latest":
                        continue

                    # Skip non-semantic tags
                    if not self._parse_semver(tag_name):
                        continue

                    # Skip pre-release tags unless explicitly allowed
                    if not include_prereleases and is_prerelease_tag(tag_name):
                        continue

                    # Skip candidates on a different variant track.
                    # For LinuxServer images, ls<N> build counters are normalized so
                    # counter churn (ls131->ls140) does not block updates.
                    if current_variant != self._extract_variant_suffix(
                        tag_name, normalize_ls=normalize_ls
                    ):
                        continue

                    # Check if this is a valid update
                    if self._compare_versions(current_tag, tag_name, scope):
                        if best_tag is None or self._is_better_version(tag_name, best_tag):
                            best_tag = tag_name

                # Early exit if we found a good update and current page has old versions
                if best_tag and current_version:
                    # If this page has versions older than current, stop searching
                    page_versions = [
                        v for t in data.get("results", []) if (v := self._parse_semver(t["name"]))
                    ]
                    if page_versions and all(v <= current_version for v in page_versions):
                        logger.debug(f"Early exit: found {best_tag}, rest are older")
                        break

                # Check for next page
                url = data.get("next")
                if not url:
                    break

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching tags for {image}: {e.response.status_code}")
            # Raise RegistryCheckError for transient failures so callers can preserve state
            raise RegistryCheckError(
                f"HTTP error fetching tags for {image}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching tags for {image}: {e}")
            raise RegistryCheckError(f"Connection error fetching tags for {image}: {e}") from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching tags for {image}: {e}")
            raise RegistryCheckError(f"Timeout fetching tags for {image}: {e}") from e
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response data fetching tags for {image}: {e}")
            return None

        return best_tag

    async def get_tag_metadata(self, image: str, tag: str) -> dict | None:
        """Get tag metadata from Docker Hub."""
        if "/" not in image:
            image = f"library/{image}"

        url = f"{self.BASE_URL}/repositories/{image}/tags/{tag}"

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()

            return {
                "name": data["name"],
                "digest": data.get("digest"),
                "last_updated": data.get("last_updated"),
                "full_size": data.get("full_size"),
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching Docker Hub metadata for {image}:{tag}: {e.response.status_code}"
            )
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching Docker Hub metadata for {image}:{tag}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching Docker Hub metadata for {image}:{tag}: {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.error(
                f"Invalid response data fetching Docker Hub metadata for {image}:{tag}: {e}"
            )
            return None


class GHCRClient(RegistryClient):
    """GitHub Container Registry client."""

    BASE_URL = "https://ghcr.io"
    TOKEN_URL = "https://ghcr.io/token"

    def __init__(self, username: str | None = None, token: str | None = None) -> None:
        """Initialize GHCR client.

        Store credentials separately to avoid applying Basic Auth to the main httpx client.
        GHCR requires Basic Auth ONLY for token requests, then Bearer token for API calls.
        """
        self._username = username
        self._token = token
        # Initialize parent WITHOUT auth to prevent httpx client from adding Basic Auth headers
        super().__init__(username=None, token=None)

    async def _get_bearer_token(self, image: str, scope: str = "pull") -> str | None:
        """Get OAuth2 bearer token for GHCR.

        Args:
            image: Image name (e.g., "user/repo")
            scope: Access scope (default: pull)

        Returns:
            Bearer token or None
        """
        params = {"scope": f"repository:{image}:{scope}", "service": "ghcr.io"}

        try:
            # Use separate httpx client for token request with Basic Auth
            # This ensures we don't mix Basic Auth and Bearer token in subsequent requests
            auth = None
            if self._username and self._token:
                auth = httpx.BasicAuth(self._username, self._token)
                logger.info(
                    f"GHCR: Using Basic Auth for token request (username: {self._username[: min(4, len(self._username))]}..., token length: {len(self._token)})"
                )
            else:
                logger.info("GHCR: No credentials provided for token request (anonymous)")

            async with httpx.AsyncClient(timeout=30.0) as token_client:
                response = await token_client.get(self.TOKEN_URL, params=params, auth=auth)
                response.raise_for_status()
                data = response.json()
                token = data.get("token")
                if token:
                    logger.info(
                        f"GHCR: Successfully obtained bearer token for {image} (token length: {len(token)})"
                    )
                else:
                    logger.warning(f"GHCR: Token response did not contain a token for {image}")
                return token
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching GHCR token for {image}: {e.response.status_code}")
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching GHCR token for {image}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching GHCR token for {image}: {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response fetching GHCR token for {image}: {e}")
            return None

    async def get_all_tags(self, image: str) -> list[str]:
        """Get all tags from GHCR with caching.

        GHCR uses Docker Registry V2 API with OAuth2 Bearer tokens.

        Args:
            image: Image name (e.g., "user/repo")

        Returns:
            List of tag names
        """
        # Check cache first
        cache_key = self._get_cache_key(image)
        cached_tags = _tag_cache.get(cache_key)
        if cached_tags is not None:
            logger.debug(f"Cache hit for {image} ({len(cached_tags)} tags)")
            return cached_tags

        # Get bearer token
        token = await self._get_bearer_token(image, "pull")
        if not token:
            return []

        tags: list[str] = []
        url = f"{self.BASE_URL}/v2/{image}/tags/list?n=1000"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            while url:
                response = await self.client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                tags.extend(data.get("tags", []))

                # Check for pagination via Link header
                link_header = response.headers.get("Link")
                if link_header and 'rel="next"' in link_header:
                    next_url = link_header.split(";")[0].strip("<>")
                    if not next_url.startswith("http"):
                        url = f"{self.BASE_URL}{next_url}"
                    else:
                        url = next_url
                else:
                    break

            # Cache the results
            _tag_cache.set(cache_key, tags)
            logger.debug(f"Cached {len(tags)} tags for {image}")

            return tags
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching GHCR tags for {image}: {e.response.status_code}")
            raise RegistryCheckError(
                f"HTTP error fetching GHCR tags for {image}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching GHCR tags for {image}: {e}")
            raise RegistryCheckError(f"Connection error fetching GHCR tags for {image}: {e}") from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching GHCR tags for {image}: {e}")
            raise RegistryCheckError(f"Timeout fetching GHCR tags for {image}: {e}") from e
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response data fetching GHCR tags for {image}: {e}")
            return tags

    async def get_latest_tag(
        self,
        image: str,
        current_tag: str,
        scope: str = "patch",
        current_digest: str | None = None,
        include_prereleases: bool = False,
    ) -> str | None:
        """Get latest tag from GHCR.

        Args:
            image: Image name
            current_tag: Current tag
            scope: Update scope (patch, minor, major)
            current_digest: Current digest (for latest tag tracking)
            include_prereleases: Include nightly, dev, alpha, beta, rc tags

        Returns:
            New tag if update available, None otherwise
        """
        # Non-semver tags (latest, lts, stable, alpine, edge, etc.) use digest tracking
        if is_non_semver_tag(current_tag) and current_digest is not None:
            metadata = await self.get_tag_metadata(image, current_tag)
            if metadata and metadata.get("digest"):
                new_digest = metadata["digest"]
                if new_digest != current_digest:
                    logger.info(
                        f"Digest changed for {image}:{current_tag}: {current_digest} -> {new_digest}"
                    )
                    return current_tag
            return None

        tags = await self.get_all_tags(image)
        if not tags:
            return None

        # Filter out "latest" and non-semantic tags
        version_tags = [
            t for t in tags if t.lower() != "latest" and self._parse_semver(t) is not None
        ]

        # Filter out pre-release tags unless explicitly allowed
        if not include_prereleases:
            version_tags = [t for t in version_tags if not is_prerelease_tag(t)]

        # Filter tags to only include those on the same variant track.
        # For LinuxServer images, ls<N> build counters are normalized so
        # counter churn (ls131->ls140) does not block updates.
        normalize_ls = self._is_linuxserver_image(image)
        current_variant = self._extract_variant_suffix(current_tag, normalize_ls=normalize_ls)
        version_tags = [
            tag for tag in version_tags
            if self._extract_variant_suffix(tag, normalize_ls=normalize_ls) == current_variant
        ]

        # Find best match
        best_tag = None
        for tag in version_tags:
            if self._compare_versions(current_tag, tag, scope):
                if best_tag is None or self._is_better_version(tag, best_tag):
                    best_tag = tag

        return best_tag

    async def get_tag_metadata(self, image: str, tag: str) -> dict | None:
        """Get tag metadata from GHCR."""
        # Get bearer token
        token = await self._get_bearer_token(image, "pull")
        if not token:
            return None

        url = f"{self.BASE_URL}/v2/{image}/manifests/{tag}"

        try:
            # Need to accept the manifest format and include bearer token
            headers = {
                "Accept": "application/vnd.docker.distribution.manifest.v2+json",
                "Authorization": f"Bearer {token}",
            }
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()

            # Get digest from headers
            digest = response.headers.get("Docker-Content-Digest")

            return {
                "name": tag,
                "digest": digest,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching GHCR metadata for {image}:{tag}: {e.response.status_code}"
            )
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching GHCR metadata for {image}:{tag}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching GHCR metadata for {image}:{tag}: {e}")
            return None


class LSCRClient(RegistryClient):
    """LinuxServer.io Container Registry client."""

    BASE_URL = "https://lscr.io"
    TOKEN_URL = "https://ghcr.io/token"  # LSCR uses GHCR for authentication

    async def _get_bearer_token(self, image: str, scope: str = "pull") -> str | None:
        """Get OAuth2 bearer token for LSCR.

        Args:
            image: Image name (e.g., "linuxserver/plex")
            scope: Access scope (default: pull)

        Returns:
            Bearer token or None
        """
        params = {
            "scope": f"repository:{image}:{scope}",
            "service": "ghcr.io",  # LSCR uses GHCR service
        }

        try:
            response = await self.client.get(self.TOKEN_URL, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("token")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching LSCR token for {image}: {e.response.status_code}")
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching LSCR token for {image}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching LSCR token for {image}: {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response fetching LSCR token for {image}: {e}")
            return None

    async def get_all_tags(self, image: str) -> list[str]:
        """Get all tags from LSCR with caching.

        LSCR uses Docker Registry V2 API with OAuth2 Bearer tokens.

        Args:
            image: Image name (e.g., "linuxserver/plex")

        Returns:
            List of tag names
        """
        # Check cache first
        cache_key = self._get_cache_key(image)
        cached_tags = _tag_cache.get(cache_key)
        if cached_tags is not None:
            logger.debug(f"Cache hit for {image} ({len(cached_tags)} tags)")
            return cached_tags

        # Get bearer token
        token = await self._get_bearer_token(image, "pull")
        if not token:
            return []

        tags: list[str] = []
        url = f"{self.BASE_URL}/v2/{image}/tags/list?n=1000"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            while url:
                response = await self.client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                tags.extend(data.get("tags", []))

                link_header = response.headers.get("Link")
                if link_header and 'rel="next"' in link_header:
                    next_url = link_header.split(";")[0].strip("<>")
                    if not next_url.startswith("http"):
                        url = f"{self.BASE_URL}{next_url}"
                    else:
                        url = next_url
                else:
                    break

            # Cache the results
            _tag_cache.set(cache_key, tags)
            logger.debug(f"Cached {len(tags)} tags for {image}")

            return tags
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching LSCR tags for {image}: {e.response.status_code}")
            raise RegistryCheckError(
                f"HTTP error fetching LSCR tags for {image}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching LSCR tags for {image}: {e}")
            raise RegistryCheckError(f"Connection error fetching LSCR tags for {image}: {e}") from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching LSCR tags for {image}: {e}")
            raise RegistryCheckError(f"Timeout fetching LSCR tags for {image}: {e}") from e
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response data fetching LSCR tags for {image}: {e}")
            return tags

    async def get_latest_tag(
        self,
        image: str,
        current_tag: str,
        scope: str = "patch",
        current_digest: str | None = None,
        include_prereleases: bool = False,
    ) -> str | None:
        """Get latest tag from LSCR.

        Args:
            image: Image name
            current_tag: Current tag
            scope: Update scope (patch, minor, major)
            current_digest: Current digest (for latest tag tracking)
            include_prereleases: Include nightly, dev, alpha, beta, rc tags

        Returns:
            New tag if update available, None otherwise
        """
        # Non-semver tags (latest, lts, stable, alpine, edge, etc.) use digest tracking
        if is_non_semver_tag(current_tag) and current_digest is not None:
            metadata = await self.get_tag_metadata(image, current_tag)
            if metadata and metadata.get("digest"):
                new_digest = metadata["digest"]
                if new_digest != current_digest:
                    logger.info(
                        f"Digest changed for {image}:{current_tag}: {current_digest} -> {new_digest}"
                    )
                    return current_tag
            return None

        tags = await self.get_all_tags(image)
        if not tags:
            return None

        # All LSCR images are LinuxServer. Normalize ls<N> counters and composite
        # hash+ls<N> suffixes (e.g., f737b826c-ls284) to a stable 'ls' token so
        # build-counter churn does not block updates across releases.
        current_variant = self._extract_variant_suffix(current_tag, normalize_ls=True)
        version_tags = []
        for t in tags:
            # Skip pre-release tags unless explicitly allowed
            if not include_prereleases and is_prerelease_tag(t):
                continue
            # Skip candidates on a different variant track
            if self._extract_variant_suffix(t, normalize_ls=True) != current_variant:
                continue
            # Only include tags that have valid semantic versions
            if self._parse_semver(t) is not None:
                version_tags.append(t)

        # Find best match
        best_tag = None
        for tag in version_tags:
            if self._compare_versions(current_tag, tag, scope):
                if best_tag is None or self._is_better_version(tag, best_tag):
                    best_tag = tag

        return best_tag

    async def get_tag_metadata(self, image: str, tag: str) -> dict | None:
        """Get tag metadata from LSCR."""
        # Get bearer token
        token = await self._get_bearer_token(image, "pull")
        if not token:
            return None

        url = f"{self.BASE_URL}/v2/{image}/manifests/{tag}"

        try:
            headers = {
                "Accept": "application/vnd.docker.distribution.manifest.v2+json",
                "Authorization": f"Bearer {token}",
            }
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()

            digest = response.headers.get("Docker-Content-Digest")

            return {
                "name": tag,
                "digest": digest,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching LSCR metadata for {image}:{tag}: {e.response.status_code}"
            )
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching LSCR metadata for {image}:{tag}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching LSCR metadata for {image}:{tag}: {e}")
            return None


class GCRClient(RegistryClient):
    """Google Container Registry client."""

    BASE_URL = "https://gcr.io"

    async def get_all_tags(self, image: str) -> list[str]:
        """Get all tags from GCR with caching.

        GCR uses Docker Registry V2 API.

        Args:
            image: Image name (e.g., "cadvisor/cadvisor")

        Returns:
            List of tag names
        """
        # Check cache first
        cache_key = self._get_cache_key(image)
        cached_tags = _tag_cache.get(cache_key)
        if cached_tags is not None:
            logger.debug(f"Cache hit for {image} ({len(cached_tags)} tags)")
            return cached_tags

        url = f"{self.BASE_URL}/v2/{image}/tags/list"

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            tags = data.get("tags", [])

            # Cache the results
            _tag_cache.set(cache_key, tags)
            logger.debug(f"Cached {len(tags)} tags for {image}")

            return tags
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching GCR tags for {image}: {e.response.status_code}")
            raise RegistryCheckError(
                f"HTTP error fetching GCR tags for {image}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching GCR tags for {image}: {e}")
            raise RegistryCheckError(f"Connection error fetching GCR tags for {image}: {e}") from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching GCR tags for {image}: {e}")
            raise RegistryCheckError(f"Timeout fetching GCR tags for {image}: {e}") from e
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response data fetching GCR tags for {image}: {e}")
            return []

    async def get_latest_tag(
        self,
        image: str,
        current_tag: str,
        scope: str = "patch",
        current_digest: str | None = None,
        include_prereleases: bool = False,
    ) -> str | None:
        """Get latest tag from GCR.

        Args:
            image: Image name
            current_tag: Current tag
            scope: Update scope (patch, minor, major)
            current_digest: Current digest (for latest tag tracking)
            include_prereleases: Include nightly, dev, alpha, beta, rc tags

        Returns:
            New tag if update available, None otherwise
        """
        # Non-semver tags (latest, lts, stable, alpine, edge, etc.) use digest tracking
        if is_non_semver_tag(current_tag) and current_digest is not None:
            metadata = await self.get_tag_metadata(image, current_tag)
            if metadata and metadata.get("digest"):
                new_digest = metadata["digest"]
                if new_digest != current_digest:
                    logger.info(
                        f"Digest changed for {image}:{current_tag}: {current_digest} -> {new_digest}"
                    )
                    return current_tag
            return None

        tags = await self.get_all_tags(image)
        if not tags:
            return None

        # Filter out "latest" and non-semantic tags
        version_tags = [
            t for t in tags if t.lower() != "latest" and self._parse_semver(t) is not None
        ]

        # Filter out pre-release tags unless explicitly allowed
        if not include_prereleases:
            version_tags = [t for t in version_tags if not is_prerelease_tag(t)]

        # Filter tags to only include those on the same variant track.
        # For LinuxServer images, ls<N> build counters are normalized so
        # counter churn (ls131->ls140) does not block updates.
        normalize_ls = self._is_linuxserver_image(image)
        current_variant = self._extract_variant_suffix(current_tag, normalize_ls=normalize_ls)
        version_tags = [
            tag for tag in version_tags
            if self._extract_variant_suffix(tag, normalize_ls=normalize_ls) == current_variant
        ]

        # Find best match
        best_tag = None
        for tag in version_tags:
            if self._compare_versions(current_tag, tag, scope):
                if best_tag is None or self._is_better_version(tag, best_tag):
                    best_tag = tag

        return best_tag

    async def get_tag_metadata(self, image: str, tag: str) -> dict | None:
        """Get tag metadata from GCR."""
        url = f"{self.BASE_URL}/v2/{image}/manifests/{tag}"

        try:
            headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()

            digest = response.headers.get("Docker-Content-Digest")

            return {
                "name": tag,
                "digest": digest,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching GCR metadata for {image}:{tag}: {e.response.status_code}"
            )
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching GCR metadata for {image}:{tag}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching GCR metadata for {image}:{tag}: {e}")
            return None


class QuayClient(RegistryClient):
    """Quay.io Container Registry client."""

    BASE_URL = "https://quay.io"

    async def get_all_tags(self, image: str) -> list[str]:
        """Get all tags from Quay.io with caching.

        Quay uses Docker Registry V2 API.

        Args:
            image: Image name (e.g., "prometheus/node-exporter")

        Returns:
            List of tag names
        """
        # Check cache first
        cache_key = self._get_cache_key(image)
        cached_tags = _tag_cache.get(cache_key)
        if cached_tags is not None:
            logger.debug(f"Cache hit for {image} ({len(cached_tags)} tags)")
            return cached_tags

        url = f"{self.BASE_URL}/v2/{image}/tags/list"

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            tags = data.get("tags", [])

            # Cache the results
            _tag_cache.set(cache_key, tags)
            logger.debug(f"Cached {len(tags)} tags for {image}")

            return tags
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching Quay tags for {image}: {e.response.status_code}")
            raise RegistryCheckError(
                f"HTTP error fetching Quay tags for {image}: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching Quay tags for {image}: {e}")
            raise RegistryCheckError(f"Connection error fetching Quay tags for {image}: {e}") from e
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching Quay tags for {image}: {e}")
            raise RegistryCheckError(f"Timeout fetching Quay tags for {image}: {e}") from e
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid response data fetching Quay tags for {image}: {e}")
            return []

    async def get_latest_tag(
        self,
        image: str,
        current_tag: str,
        scope: str = "patch",
        current_digest: str | None = None,
        include_prereleases: bool = False,
    ) -> str | None:
        """Get latest tag from Quay.io.

        Args:
            image: Image name
            current_tag: Current tag
            scope: Update scope (patch, minor, major)
            current_digest: Current digest (for latest tag tracking)
            include_prereleases: Include nightly, dev, alpha, beta, rc tags

        Returns:
            New tag if update available, None otherwise
        """
        # Non-semver tags (latest, lts, stable, alpine, edge, etc.) use digest tracking
        if is_non_semver_tag(current_tag) and current_digest is not None:
            metadata = await self.get_tag_metadata(image, current_tag)
            if metadata and metadata.get("digest"):
                new_digest = metadata["digest"]
                if new_digest != current_digest:
                    logger.info(
                        f"Digest changed for {image}:{current_tag}: {current_digest} -> {new_digest}"
                    )
                    return current_tag
            return None

        tags = await self.get_all_tags(image)
        if not tags:
            return None

        # Filter out "latest" and non-semantic tags
        version_tags = [
            t for t in tags if t.lower() != "latest" and self._parse_semver(t) is not None
        ]

        # Filter out pre-release tags unless explicitly allowed
        if not include_prereleases:
            version_tags = [t for t in version_tags if not is_prerelease_tag(t)]

        # Filter tags to only include those on the same variant track.
        # For LinuxServer images, ls<N> build counters are normalized so
        # counter churn (ls131->ls140) does not block updates.
        normalize_ls = self._is_linuxserver_image(image)
        current_variant = self._extract_variant_suffix(current_tag, normalize_ls=normalize_ls)
        version_tags = [
            tag for tag in version_tags
            if self._extract_variant_suffix(tag, normalize_ls=normalize_ls) == current_variant
        ]

        # Find best match
        best_tag = None
        for tag in version_tags:
            if self._compare_versions(current_tag, tag, scope):
                if best_tag is None or self._is_better_version(tag, best_tag):
                    best_tag = tag

        return best_tag

    async def get_tag_metadata(self, image: str, tag: str) -> dict | None:
        """Get tag metadata from Quay.io."""
        url = f"{self.BASE_URL}/v2/{image}/manifests/{tag}"

        try:
            headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()

            digest = response.headers.get("Docker-Content-Digest")

            return {
                "name": tag,
                "digest": digest,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching Quay metadata for {image}:{tag}: {e.response.status_code}"
            )
            return None
        except httpx.ConnectError as e:
            logger.error(f"Connection error fetching Quay metadata for {image}:{tag}: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching Quay metadata for {image}:{tag}: {e}")
            return None


class RegistryClientFactory:
    """Factory for creating registry clients."""

    @staticmethod
    async def get_client(registry: str, db=None) -> RegistryClient:
        """Get registry client by name with authentication.

        Args:
            registry: Registry name (dockerhub, ghcr, lscr, gcr, quay)
            db: Optional database session for loading credentials

        Returns:
            Registry client instance
        """
        registry = registry.lower()

        # Map docker.io to dockerhub
        if registry == "docker.io":
            registry = "dockerhub"

        # Load credentials from settings if db provided
        username = None
        token = None

        if db:
            from app.services.settings_service import SettingsService

            if registry == "dockerhub":
                username = await SettingsService.get(db, "dockerhub_username")
                token = await SettingsService.get(db, "dockerhub_token")
            elif registry == "ghcr":
                username = await SettingsService.get(db, "ghcr_username")
                token = await SettingsService.get(db, "ghcr_token")

        # Create client with credentials
        if registry == "dockerhub":
            return DockerHubClient(username=username, token=token)
        elif registry == "ghcr":
            return GHCRClient(username=username, token=token)
        elif registry == "lscr":
            return LSCRClient()
        elif registry == "gcr":
            return GCRClient()
        elif registry == "quay":
            return QuayClient()
        else:
            raise ValueError(f"Unsupported registry: {registry}")
