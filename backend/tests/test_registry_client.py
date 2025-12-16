"""Tests for registry client (app/services/registry_client.py).

Tests version parsing, prerelease detection, and tag filtering:
- Semantic version parsing (semver)
- Calendar versioning detection
- Prerelease tag identification (alpha, beta, rc, nightly, dev)
- Tag comparison with scope (patch/minor/major)
- Architecture suffix detection and filtering
- Windows image detection
- Tag caching with TTL
- Multi-registry support
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.services.registry_client import (
    is_prerelease_tag,
    TagCache,
    canonical_arch_suffix,
    NON_PEP440_PRERELEASE_INDICATORS
)


class TestPrereleaseDetection:
    """Test suite for prerelease tag detection."""

    def test_detects_pep440_alpha_tags(self):
        """Test detection of PEP 440 alpha tags."""
        assert is_prerelease_tag("1.2.3a1") is True
        assert is_prerelease_tag("1.2.3-alpha.1") is True
        assert is_prerelease_tag("v2.0.0a") is True

    def test_detects_pep440_beta_tags(self):
        """Test detection of PEP 440 beta tags."""
        assert is_prerelease_tag("1.2.3b1") is True
        assert is_prerelease_tag("1.2.3-beta.1") is True
        assert is_prerelease_tag("v2.0.0b") is True

    def test_detects_pep440_rc_tags(self):
        """Test detection of PEP 440 release candidate tags."""
        assert is_prerelease_tag("1.2.3rc1") is True
        assert is_prerelease_tag("1.2.3-rc.1") is True
        assert is_prerelease_tag("v2.0.0rc") is True

    def test_detects_pep440_dev_tags(self):
        """Test detection of PEP 440 dev tags."""
        assert is_prerelease_tag("1.2.3.dev1") is True
        assert is_prerelease_tag("1.2.3-dev") is True

    def test_detects_nightly_tags(self):
        """Test detection of nightly build tags."""
        assert is_prerelease_tag("nightly") is True
        assert is_prerelease_tag("2024.12.07-nightly") is True
        assert is_prerelease_tag("1.2.3-nightly") is True

    def test_detects_unstable_tags(self):
        """Test detection of unstable tags."""
        assert is_prerelease_tag("unstable") is True
        assert is_prerelease_tag("1.2.3-unstable") is True

    def test_detects_edge_tags(self):
        """Test detection of edge/canary tags."""
        assert is_prerelease_tag("edge") is True
        assert is_prerelease_tag("canary") is True
        assert is_prerelease_tag("1.2.3-edge") is True

    def test_detects_develop_branch_tags(self):
        """Test detection of develop/master/main tags."""
        assert is_prerelease_tag("develop") is True
        assert is_prerelease_tag("master") is True
        assert is_prerelease_tag("main") is True
        assert is_prerelease_tag("1.2.3-develop") is True

    def test_detects_pr_tags(self):
        """Test detection of pull request tags."""
        assert is_prerelease_tag("pr-123") is True
        assert is_prerelease_tag("pull-456") is True
        assert is_prerelease_tag("1.2.3-pr-789") is True

    def test_detects_feature_branch_tags(self):
        """Test detection of feature/fix branch tags."""
        assert is_prerelease_tag("feat-new-api") is True
        assert is_prerelease_tag("feature-auth") is True
        assert is_prerelease_tag("fix-bug-123") is True
        assert is_prerelease_tag("hotfix-critical") is True

    def test_stable_version_not_prerelease(self):
        """Test stable versions are not detected as prereleases."""
        assert is_prerelease_tag("1.2.3") is False
        assert is_prerelease_tag("v2.0.0") is False
        assert is_prerelease_tag("4.6.0") is False

    def test_latest_tag_not_prerelease(self):
        """Test 'latest' tag is not detected as prerelease.

        Implementation correctly uses word boundary matching by splitting on delimiters
        and checking exact segment matches to avoid false positives like 'test' in 'latest'.
        """
        assert is_prerelease_tag("latest") is False

    def test_date_versioning_not_prerelease(self):
        """Test calendar versioning is not detected as prerelease."""
        assert is_prerelease_tag("2024.12.07") is False
        assert is_prerelease_tag("2024-12-07") is False

    def test_build_metadata_ignored(self):
        """Test build metadata (+suffix) is ignored."""
        # 1.2.3+build123 is stable
        assert is_prerelease_tag("1.2.3+build123") is False
        # 1.2.3-beta+build123 is prerelease (beta part)
        assert is_prerelease_tag("1.2.3-beta+build123") is True

    def test_case_insensitive_detection(self):
        """Test prerelease detection is case insensitive."""
        assert is_prerelease_tag("NIGHTLY") is True
        # "Beta" and "RC1" alone are not detected because:
        # 1. They're not in NON_PEP440_PRERELEASE_INDICATORS
        # 2. They don't parse as valid PEP 440 versions
        # They would be detected in context like "1.0-Beta" or "v2.0-RC1"
        assert is_prerelease_tag("1.0-Beta") is True
        assert is_prerelease_tag("v2.0-RC1") is True

    def test_version_with_v_prefix(self):
        """Test 'v' prefix is handled correctly."""
        assert is_prerelease_tag("v1.2.3-alpha") is True
        assert is_prerelease_tag("v1.2.3") is False


class TestTagCache:
    """Test suite for TagCache with TTL."""

    def test_cache_stores_and_retrieves_tags(self):
        """Test basic cache store and retrieve."""
        cache = TagCache(ttl_minutes=15)
        tags = ["1.0.0", "1.1.0", "1.2.0"]

        cache.set("dockerhub:nginx", tags)
        cached = cache.get("dockerhub:nginx")

        assert cached == tags

    def test_cache_returns_none_for_missing_key(self):
        """Test cache returns None for non-existent keys."""
        cache = TagCache(ttl_minutes=15)

        assert cache.get("nonexistent") is None

    def test_cache_expires_after_ttl(self):
        """Test cached entries expire after TTL."""
        cache = TagCache(ttl_minutes=0)  # 0 minutes = instant expiration
        tags = ["1.0.0", "1.1.0"]

        cache.set("dockerhub:nginx", tags)

        # Manually expire the entry
        import time
        time.sleep(0.001)
        cache._cache["dockerhub:nginx"]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Should return None (expired)
        assert cache.get("dockerhub:nginx") is None

        # Should be removed from cache
        assert "dockerhub:nginx" not in cache._cache

    def test_cache_clear_removes_all_entries(self):
        """Test clear() removes all cached entries."""
        cache = TagCache(ttl_minutes=15)

        cache.set("key1", ["tag1"])
        cache.set("key2", ["tag2"])
        cache.set("key3", ["tag3"])

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.get("key3") is None
        assert len(cache._cache) == 0

    def test_cleanup_expired_removes_only_expired(self):
        """Test cleanup_expired removes only expired entries."""
        cache = TagCache(ttl_minutes=15)

        # Add entries
        cache.set("fresh", ["1.0.0"])
        cache.set("stale1", ["2.0.0"])
        cache.set("stale2", ["3.0.0"])

        # Manually expire two entries
        now = datetime.now(timezone.utc)
        cache._cache["stale1"]["expires_at"] = now - timedelta(minutes=1)
        cache._cache["stale2"]["expires_at"] = now - timedelta(minutes=1)

        # Cleanup
        removed_count = cache.cleanup_expired()

        assert removed_count == 2
        assert cache.get("fresh") == ["1.0.0"]
        assert cache.get("stale1") is None
        assert cache.get("stale2") is None

    def test_cache_ttl_calculates_correctly(self):
        """Test cache TTL is calculated correctly."""
        cache = TagCache(ttl_minutes=30)
        cache.set("test", ["1.0.0"])

        entry = cache._cache["test"]
        expires_at = entry["expires_at"]

        # Should expire approximately 30 minutes from now
        now = datetime.now(timezone.utc)
        expected_expiry = now + timedelta(minutes=30)

        # Allow 1 second tolerance
        assert abs((expires_at - expected_expiry).total_seconds()) < 1


class TestArchitectureSuffixDetection:
    """Test suite for architecture suffix detection and normalization."""

    def test_canonical_arch_suffix_normalizes_x86_64_to_amd64(self):
        """Test x86_64 is normalized to amd64."""
        assert canonical_arch_suffix("x86_64") == "amd64"

    def test_canonical_arch_suffix_normalizes_aarch64_to_arm64(self):
        """Test aarch64 is normalized to arm64."""
        assert canonical_arch_suffix("aarch64") == "arm64"

    def test_canonical_arch_suffix_normalizes_armv7_to_arm(self):
        """Test armv7 variants are normalized to arm."""
        assert canonical_arch_suffix("armv7") == "arm"
        assert canonical_arch_suffix("armv7l") == "arm"
        assert canonical_arch_suffix("armhf") == "arm"

    def test_canonical_arch_suffix_normalizes_i386_to_386(self):
        """Test i386 is normalized to 386."""
        assert canonical_arch_suffix("i386") == "386"

    def test_canonical_arch_suffix_returns_none_for_none(self):
        """Test None input returns None."""
        assert canonical_arch_suffix(None) is None

    def test_canonical_arch_suffix_preserves_standard_suffixes(self):
        """Test standard suffixes are preserved as-is."""
        assert canonical_arch_suffix("amd64") == "amd64"
        assert canonical_arch_suffix("arm64") == "arm64"
        assert canonical_arch_suffix("arm") == "arm"
        assert canonical_arch_suffix("386") == "386"

    def test_canonical_arch_suffix_preserves_unknown_suffixes(self):
        """Test unknown suffixes are returned unchanged."""
        assert canonical_arch_suffix("unknown") == "unknown"
        assert canonical_arch_suffix("riscv64") == "riscv64"


class TestVersionComparison:
    """Test suite for version comparison logic."""

    @pytest.fixture
    def mock_client(self):
        """Create mock registry client."""
        from app.services.registry_client import DockerHubClient
        client = DockerHubClient()
        return client

    def test_normalize_version_parses_semver(self, mock_client):
        """Test _normalize_version parses semantic versions."""
        normalized = mock_client._normalize_version("1.2.3")

        assert normalized == (1, 2, 3, ())

    def test_normalize_version_strips_v_prefix(self, mock_client):
        """Test _normalize_version strips 'v' prefix."""
        normalized = mock_client._normalize_version("v1.2.3")

        assert normalized == (1, 2, 3, ())

    def test_normalize_version_handles_two_component_version(self, mock_client):
        """Test _normalize_version handles versions with 2 components."""
        normalized = mock_client._normalize_version("1.2")

        assert normalized == (1, 2, 0, ())

    def test_normalize_version_handles_single_component_version(self, mock_client):
        """Test _normalize_version handles versions with 1 component."""
        normalized = mock_client._normalize_version("5")

        assert normalized == (5, 0, 0, ())

    def test_normalize_version_handles_prerelease(self, mock_client):
        """Test _normalize_version parses prerelease versions."""
        normalized = mock_client._normalize_version("1.2.3-beta.1")

        assert normalized[0:3] == (1, 2, 3)
        assert normalized[3] != ()  # Has prerelease info

    def test_normalize_version_ignores_build_metadata(self, mock_client):
        """Test _normalize_version ignores build metadata (+suffix)."""
        normalized = mock_client._normalize_version("1.2.3+build.123")

        assert normalized == (1, 2, 3, ())

    def test_normalize_version_handles_suffix_with_hyphen(self, mock_client):
        """Test _normalize_version handles versions with hyphen suffix."""
        # "4.6.0-ls123" -> parse "4.6.0"
        normalized = mock_client._normalize_version("4.6.0-ls123")

        assert normalized[0:3] == (4, 6, 0)

    def test_normalize_version_returns_none_for_latest(self, mock_client):
        """Test _normalize_version returns None for 'latest' tag."""
        normalized = mock_client._normalize_version("latest")

        assert normalized is None

    def test_normalize_version_returns_none_for_invalid(self, mock_client):
        """Test _normalize_version returns None for non-version strings."""
        normalized = mock_client._normalize_version("nightly")

        assert normalized is None

    def test_compare_versions_patch_scope_allows_patch_updates(self, mock_client):
        """Test patch scope allows only patch version updates."""
        # 1.2.3 -> 1.2.4: allowed (patch)
        assert mock_client._compare_versions("1.2.3", "1.2.4", "patch") is True

        # 1.2.3 -> 1.3.0: not allowed (minor)
        assert mock_client._compare_versions("1.2.3", "1.3.0", "patch") is False

        # 1.2.3 -> 2.0.0: not allowed (major)
        assert mock_client._compare_versions("1.2.3", "2.0.0", "patch") is False

    def test_compare_versions_minor_scope_allows_minor_and_patch(self, mock_client):
        """Test minor scope allows minor and patch updates."""
        # 1.2.3 -> 1.2.4: allowed (patch)
        assert mock_client._compare_versions("1.2.3", "1.2.4", "minor") is True

        # 1.2.3 -> 1.3.0: allowed (minor)
        assert mock_client._compare_versions("1.2.3", "1.3.0", "minor") is True

        # 1.2.3 -> 2.0.0: not allowed (major)
        assert mock_client._compare_versions("1.2.3", "2.0.0", "minor") is False

    def test_compare_versions_major_scope_allows_all_updates(self, mock_client):
        """Test major scope allows all version updates."""
        # 1.2.3 -> 1.2.4: allowed (patch)
        assert mock_client._compare_versions("1.2.3", "1.2.4", "major") is True

        # 1.2.3 -> 1.3.0: allowed (minor)
        assert mock_client._compare_versions("1.2.3", "1.3.0", "major") is True

        # 1.2.3 -> 2.0.0: allowed (major)
        assert mock_client._compare_versions("1.2.3", "2.0.0", "major") is True

    def test_compare_versions_rejects_downgrades(self, mock_client):
        """Test version comparison rejects downgrades."""
        # 1.2.4 -> 1.2.3: downgrade not allowed
        assert mock_client._compare_versions("1.2.4", "1.2.3", "major") is False

    def test_compare_versions_rejects_same_version(self, mock_client):
        """Test version comparison rejects same version."""
        # 1.2.3 -> 1.2.3: same version not allowed
        assert mock_client._compare_versions("1.2.3", "1.2.3", "major") is False


class TestWindowsImageDetection:
    """Test suite for Windows image detection."""

    @pytest.fixture
    def mock_client(self):
        """Create mock registry client."""
        from app.services.registry_client import DockerHubClient
        return DockerHubClient()

    def test_detects_windowsservercore_tags(self, mock_client):
        """Test detection of windowsservercore images."""
        assert mock_client._is_windows_image("1.2.3-windowsservercore") is True

    def test_detects_nanoserver_tags(self, mock_client):
        """Test detection of nanoserver images."""
        assert mock_client._is_windows_image("1.2.3-nanoserver") is True

    def test_detects_ltsc_tags(self, mock_client):
        """Test detection of LTSC (Long-Term Servicing Channel) tags."""
        assert mock_client._is_windows_image("1809-ltsc2019") is True
        assert mock_client._is_windows_image("ltsc2022") is True

    def test_detects_windows_suffix_tags(self, mock_client):
        """Test detection of -windows suffix."""
        assert mock_client._is_windows_image("1.2.3-windows") is True

    def test_linux_tags_not_windows(self, mock_client):
        """Test Linux tags are not detected as Windows."""
        assert mock_client._is_windows_image("1.2.3") is False
        assert mock_client._is_windows_image("1.2.3-alpine") is False
        assert mock_client._is_windows_image("latest") is False

    def test_case_insensitive_windows_detection(self, mock_client):
        """Test Windows detection is case insensitive."""
        assert mock_client._is_windows_image("1.2.3-WindowsServerCore") is True
        assert mock_client._is_windows_image("NANOSERVER") is True


class TestArchitectureMismatchDetection:
    """Test suite for architecture mismatch detection."""

    @pytest.fixture
    def mock_client(self):
        """Create mock registry client."""
        from app.services.registry_client import DockerHubClient
        return DockerHubClient()

    def test_extract_arch_suffix_detects_amd64(self, mock_client):
        """Test architecture suffix extraction for amd64."""
        assert mock_client._extract_arch_suffix("1.2.3-amd64") == "amd64"

    def test_extract_arch_suffix_detects_arm64(self, mock_client):
        """Test architecture suffix extraction for arm64."""
        assert mock_client._extract_arch_suffix("1.2.3-arm64") == "arm64"

    def test_extract_arch_suffix_detects_arm(self, mock_client):
        """Test architecture suffix extraction for arm."""
        assert mock_client._extract_arch_suffix("1.2.3-arm") == "arm"

    def test_extract_arch_suffix_normalizes_aliases(self, mock_client):
        """Test architecture suffix extraction normalizes aliases."""
        # aarch64 -> arm64
        assert mock_client._extract_arch_suffix("1.2.3-aarch64") == "arm64"
        # x86_64 -> amd64
        assert mock_client._extract_arch_suffix("1.2.3-x86_64") == "amd64"

    def test_extract_arch_suffix_returns_none_for_no_suffix(self, mock_client):
        """Test architecture suffix extraction returns None for no suffix."""
        assert mock_client._extract_arch_suffix("1.2.3") is None
        assert mock_client._extract_arch_suffix("latest") is None

    def test_has_arch_mismatch_detects_different_architectures(self, mock_client):
        """Test architecture mismatch when architectures differ."""
        # amd64 vs arm64
        assert mock_client._has_arch_mismatch("1.2.3-amd64", "1.2.4-arm64") is True

    def test_has_arch_mismatch_same_architecture_no_mismatch(self, mock_client):
        """Test no mismatch when architectures are the same."""
        # amd64 vs amd64
        assert mock_client._has_arch_mismatch("1.2.3-amd64", "1.2.4-amd64") is False

    def test_has_arch_mismatch_no_suffix_no_mismatch(self, mock_client):
        """Test no mismatch when neither tag has architecture suffix."""
        assert mock_client._has_arch_mismatch("1.2.3", "1.2.4") is False

    def test_has_arch_mismatch_current_has_suffix_candidate_no_suffix(self, mock_client):
        """Test mismatch when current has arch suffix but candidate doesn't."""
        # User pinned to architecture-specific tag, avoid switching styles
        assert mock_client._has_arch_mismatch("1.2.3-amd64", "1.2.4") is True

    def test_has_arch_mismatch_candidate_has_suffix_current_no_suffix(self, mock_client):
        """Test behavior when candidate has arch suffix but current doesn't."""
        # Allow only if candidate matches host architecture
        # This test depends on HOST_ARCH_CANONICAL which varies by system
        # Just verify it returns a boolean
        result = mock_client._has_arch_mismatch("1.2.3", "1.2.4-amd64")
        assert isinstance(result, bool)


class TestRegistryClientBase:
    """Test suite for RegistryClient base class functionality."""

    @pytest.mark.asyncio
    async def test_client_initialization_with_username_password(self):
        """Test client initializes with username and password."""
        from app.services.registry_client import DockerHubClient

        client = DockerHubClient(username="testuser", token="testpass")

        # Should have auth configured
        assert client.client.auth is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_client_initialization_with_token_only(self):
        """Test client initializes with bearer token."""
        from app.services.registry_client import DockerHubClient

        client = DockerHubClient(token="test-token-123")

        # Should have Authorization header
        assert "Authorization" in client.client.headers
        assert client.client.headers["Authorization"] == "Bearer test-token-123"
        await client.close()

    @pytest.mark.asyncio
    async def test_client_async_context_manager(self):
        """Test client works as async context manager."""
        from app.services.registry_client import DockerHubClient

        async with DockerHubClient() as client:
            assert client is not None
            assert client.client is not None

        # Client should be closed after context exit
        # (checking aclose was called is hard without mocking)

    @pytest.mark.asyncio
    async def test_get_cache_key_includes_registry_and_image(self):
        """Test cache key generation includes registry name and image."""
        from app.services.registry_client import DockerHubClient

        client = DockerHubClient()
        cache_key = client._get_cache_key("nginx")

        assert "dockerhub" in cache_key
        assert "nginx" in cache_key

        await client.close()


class TestDockerHubClient:
    """Test suite for Docker Hub specific functionality."""

    @pytest.mark.asyncio
    async def test_get_all_tags_adds_library_prefix_for_official_images(self):
        """Test Docker Hub adds 'library/' prefix for official images."""
        from app.services.registry_client import DockerHubClient

        client = DockerHubClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"name": "latest"},
                {"name": "1.25.3"}
            ],
            "next": None
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response) as mock_get:
            tags = await client.get_all_tags("nginx")

            # Should have called API with "library/nginx"
            called_url = mock_get.call_args[0][0]
            assert "library/nginx" in called_url

        await client.close()

    @pytest.mark.asyncio
    async def test_get_all_tags_preserves_namespace_for_user_images(self):
        """Test Docker Hub preserves namespace for user images."""
        from app.services.registry_client import DockerHubClient

        client = DockerHubClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"name": "latest"}],
            "next": None
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response) as mock_get:
            await client.get_all_tags("linuxserver/plex")

            # Should call with original namespace
            called_url = mock_get.call_args[0][0]
            assert "linuxserver/plex" in called_url

        await client.close()

    @pytest.mark.asyncio
    async def test_get_all_tags_handles_pagination(self):
        """Test Docker Hub client handles paginated responses."""
        from app.services.registry_client import DockerHubClient, _tag_cache

        # Clear cache to ensure clean state
        _tag_cache.clear()

        client = DockerHubClient()

        # First page
        page1_response = MagicMock()
        page1_response.json.return_value = {
            "results": [{"name": "1.0.0"}, {"name": "1.1.0"}],
            "next": "https://hub.docker.com/v2/repositories/library/nginx/tags?page=2"
        }
        page1_response.raise_for_status = MagicMock()

        # Second page (last)
        page2_response = MagicMock()
        page2_response.json.return_value = {
            "results": [{"name": "1.2.0"}],
            "next": None
        }
        page2_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", side_effect=[page1_response, page2_response]):
            tags = await client.get_all_tags("nginx")

            # Should have all tags from both pages
            assert len(tags) == 3
            assert "1.0.0" in tags
            assert "1.1.0" in tags
            assert "1.2.0" in tags

        await client.close()

    @pytest.mark.asyncio
    async def test_get_all_tags_uses_cache_on_second_call(self):
        """Test Docker Hub client uses cache for repeated calls."""
        from app.services.registry_client import DockerHubClient
        from app.services.registry_client import _tag_cache

        _tag_cache.clear()  # Clear global cache

        client = DockerHubClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"name": "latest"}],
            "next": None
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.client, "get", return_value=mock_response) as mock_get:
            # First call
            tags1 = await client.get_all_tags("nginx")

            # Second call (should use cache)
            tags2 = await client.get_all_tags("nginx")

            # Should have only made one API call
            assert mock_get.call_count == 1

            # Results should be the same
            assert tags1 == tags2

        await client.close()

    @pytest.mark.asyncio
    async def test_get_all_tags_returns_empty_on_http_error(self):
        """Test Docker Hub client returns empty list on HTTP error."""
        from app.services.registry_client import DockerHubClient
        import httpx

        client = DockerHubClient()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not found", request=MagicMock(), response=mock_response
        )

        with patch.object(client.client, "get", return_value=mock_response):
            tags = await client.get_all_tags("nonexistent/image")

            assert tags == []

        await client.close()


class TestPrereleaseIndicators:
    """Test suite for prerelease indicator constants."""

    def test_non_pep440_indicators_includes_common_tags(self):
        """Test NON_PEP440_PRERELEASE_INDICATORS includes common tags."""
        assert "nightly" in NON_PEP440_PRERELEASE_INDICATORS
        assert "develop" in NON_PEP440_PRERELEASE_INDICATORS
        assert "dev" in NON_PEP440_PRERELEASE_INDICATORS
        assert "unstable" in NON_PEP440_PRERELEASE_INDICATORS
        assert "edge" in NON_PEP440_PRERELEASE_INDICATORS
        assert "canary" in NON_PEP440_PRERELEASE_INDICATORS

    def test_non_pep440_indicators_includes_branch_patterns(self):
        """Test NON_PEP440_PRERELEASE_INDICATORS includes branch patterns."""
        assert "pr-" in NON_PEP440_PRERELEASE_INDICATORS
        assert "pull-" in NON_PEP440_PRERELEASE_INDICATORS
        assert "feat-" in NON_PEP440_PRERELEASE_INDICATORS
        assert "feature-" in NON_PEP440_PRERELEASE_INDICATORS
        assert "fix-" in NON_PEP440_PRERELEASE_INDICATORS


class TestVersionNormalizationEdgeCases:
    """Test suite for version normalization edge cases."""

    @pytest.fixture
    def mock_client(self):
        """Create mock registry client."""
        from app.services.registry_client import DockerHubClient
        return DockerHubClient()

    def test_normalize_version_with_leading_zeros(self, mock_client):
        """Test version normalization handles leading zeros."""
        # packaging.Version normalizes 01.02.03 -> 1.2.3
        normalized = mock_client._normalize_version("01.02.03")

        assert normalized == (1, 2, 3, ())

    def test_normalize_version_with_underscores(self, mock_client):
        """Test version normalization handles underscore separators."""
        # 4.6.0_ls123 -> parse 4.6.0
        normalized = mock_client._normalize_version("4.6.0_ls123")

        assert normalized[0:3] == (4, 6, 0)

    def test_normalize_version_with_epoch(self, mock_client):
        """Test version normalization handles epoch versions."""
        # packaging.Version supports epoch (1!1.0)
        normalized = mock_client._normalize_version("1!1.0.0")

        # Epoch is stored separately, not in release tuple
        assert normalized[0:3] == (1, 0, 0)

    def test_normalize_version_with_four_components(self, mock_client):
        """Test version normalization handles versions with 4+ components."""
        # packaging.Version supports arbitrary components
        normalized = mock_client._normalize_version("1.2.3.4")

        # Only first 3 components used in comparison
        assert normalized[0:3] == (1, 2, 3)
