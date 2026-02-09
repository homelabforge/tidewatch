"""Tests for tag fetcher service (app/services/tag_fetcher.py).

Tests the registry tag fetching layer:
- Run-scoped cache hit/miss
- Error handling for fetch failures
- Prerelease resolution (tri-state: None/True/False)
- Non-semver digest tracking for non-latest tags (Fix 9)
- Docker Hub tag fetch optimization (Fix 7)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.container import Container
from app.services.check_run_context import CheckRunContext, ImageCheckKey, TagFetchResult
from app.services.registry_rate_limiter import RegistryRateLimiter
from app.services.tag_fetcher import FetchTagsRequest, TagFetcher


def make_request(**overrides) -> FetchTagsRequest:
    """Create a FetchTagsRequest with sensible defaults."""
    defaults = {
        "registry": "ghcr.io",
        "image": "homelabforge/tidewatch",
        "current_tag": "1.0.0",
        "scope": "patch",
        "include_prereleases": False,
        "current_digest": None,
    }
    defaults.update(overrides)
    return FetchTagsRequest(**defaults)


@pytest.fixture
def mock_db():
    """Create mock async database session."""
    db = AsyncMock()
    return db


@pytest.fixture
def rate_limiter():
    """Create rate limiter."""
    return RegistryRateLimiter(global_concurrency=5)


class TestCacheHitMiss:
    """Test run-scoped caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_from_registry(self, mock_db, rate_limiter):
        """Cache miss should call registry and cache result."""
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="1.0.1")
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.get_all_tags = AsyncMock(return_value=["1.0.0", "1.0.1"])
        mock_client.get_tag_metadata = AsyncMock(return_value=None)
        mock_client.uses_tag_cache_for_latest = True
        mock_client._is_non_semver_tag = MagicMock(return_value=False)
        mock_client.close = AsyncMock()

        run_context = CheckRunContext(job_id=1)

        with patch(
            "app.services.tag_fetcher.RegistryClientFactory.get_client",
            return_value=mock_client,
        ):
            fetcher = TagFetcher(mock_db, rate_limiter, run_context)
            request = make_request()
            response = await fetcher.fetch_tags(request)

        assert response.cache_hit is False
        assert response.latest_tag == "1.0.1"
        assert response.error is None

    @pytest.mark.asyncio
    async def test_cache_hit_skips_registry(self, mock_db, rate_limiter):
        """Cache hit should return cached result without calling registry."""
        run_context = CheckRunContext(job_id=1)

        # Pre-populate cache
        key = ImageCheckKey(
            registry="ghcr.io",
            image="homelabforge/tidewatch",
            current_tag="1.0.0",
            scope="patch",
            include_prereleases=False,
        )
        cached_result = TagFetchResult(
            tags=["1.0.0", "1.0.1"],
            latest_tag="1.0.1",
            latest_major_tag=None,
            metadata=None,
        )
        await run_context.set_cached_result(key, cached_result)

        fetcher = TagFetcher(mock_db, rate_limiter, run_context)
        request = make_request()
        response = await fetcher.fetch_tags(request)

        assert response.cache_hit is True
        assert response.latest_tag == "1.0.1"


class TestErrorHandling:
    """Test error handling during tag fetches."""

    @pytest.mark.asyncio
    async def test_registry_error_returns_error_response(self, mock_db, rate_limiter):
        """Registry errors should be caught and returned in response."""
        with patch(
            "app.services.tag_fetcher.RegistryClientFactory.get_client",
            side_effect=Exception("Connection refused"),
        ):
            fetcher = TagFetcher(mock_db, rate_limiter)
            request = make_request()
            response = await fetcher.fetch_tags(request)

        assert response.error is not None
        assert "Connection refused" in response.error
        assert response.latest_tag is None


class TestPrereleaseResolution:
    """Test tri-state prerelease resolution (Fix 5)."""

    @pytest.mark.asyncio
    async def test_container_none_inherits_global(self, mock_db, rate_limiter):
        """Container prerelease=None should inherit global setting."""
        container = Container(
            id=1,
            name="test",
            image="nginx",
            current_tag="1.0.0",
            current_digest=None,
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=None,  # Inherit global
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.get_all_tags = AsyncMock(return_value=[])
        mock_client.uses_tag_cache_for_latest = False
        mock_client._is_non_semver_tag = MagicMock(return_value=False)
        mock_client.close = AsyncMock()

        with (
            patch(
                "app.services.tag_fetcher.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.tag_fetcher.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            fetcher = TagFetcher(mock_db, rate_limiter)
            await fetcher.fetch_tags_for_container(container)

            # Should pass include_prereleases=True (from global setting)
            mock_client.get_latest_tag.assert_called_once()
            call_kwargs = mock_client.get_latest_tag.call_args.kwargs
            assert call_kwargs["include_prereleases"] is True

    @pytest.mark.asyncio
    async def test_container_false_overrides_global_true(self, mock_db, rate_limiter):
        """Container prerelease=False should override global=True."""
        container = Container(
            id=1,
            name="test",
            image="nginx",
            current_tag="1.0.0",
            current_digest=None,
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=False,  # Explicitly stable-only
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.get_all_tags = AsyncMock(return_value=[])
        mock_client.uses_tag_cache_for_latest = False
        mock_client._is_non_semver_tag = MagicMock(return_value=False)
        mock_client.close = AsyncMock()

        with (
            patch(
                "app.services.tag_fetcher.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.tag_fetcher.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=True,  # Global says True
            ),
        ):
            fetcher = TagFetcher(mock_db, rate_limiter)
            await fetcher.fetch_tags_for_container(container)

            # Should pass include_prereleases=False (container overrides global)
            mock_client.get_latest_tag.assert_called_once()
            call_kwargs = mock_client.get_latest_tag.call_args.kwargs
            assert call_kwargs["include_prereleases"] is False


class TestNonSemverDigest:
    """Test non-semver digest tracking expansion (Fix 9)."""

    @pytest.mark.asyncio
    async def test_lts_tag_passes_digest(self, mock_db, rate_limiter):
        """Tags like 'lts' should pass current_digest to registry."""
        container = Container(
            id=1,
            name="test",
            image="postgres",
            current_tag="lts",
            current_digest="sha256:old_lts_digest",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=None,
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.get_all_tags = AsyncMock(return_value=[])
        mock_client.get_tag_metadata = AsyncMock(return_value={"digest": "sha256:new_lts_digest"})
        mock_client.uses_tag_cache_for_latest = False
        mock_client._is_non_semver_tag = MagicMock(return_value=True)
        mock_client.close = AsyncMock()

        with (
            patch(
                "app.services.tag_fetcher.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.tag_fetcher.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            fetcher = TagFetcher(mock_db, rate_limiter)
            response = await fetcher.fetch_tags_for_container(container)

            # Should fetch metadata for 'lts' tag (not just 'latest')
            mock_client.get_tag_metadata.assert_called_once_with("postgres", "lts")
            assert response.metadata is not None
            assert response.metadata["digest"] == "sha256:new_lts_digest"


class TestDockerHubOptimization:
    """Test Docker Hub tag fetch optimization (Fix 7)."""

    @pytest.mark.asyncio
    async def test_dockerhub_skips_eager_get_all_tags(self, mock_db, rate_limiter):
        """Docker Hub should NOT call get_all_tags before get_latest_tag."""
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="1.0.1")
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.get_all_tags = AsyncMock(return_value=["1.0.0", "1.0.1"])
        mock_client.uses_tag_cache_for_latest = False  # Docker Hub
        mock_client._is_non_semver_tag = MagicMock(return_value=False)
        mock_client.close = AsyncMock()

        with patch(
            "app.services.tag_fetcher.RegistryClientFactory.get_client",
            return_value=mock_client,
        ):
            fetcher = TagFetcher(mock_db, rate_limiter)
            request = make_request(registry="docker.io")
            await fetcher.fetch_tags(request)

        # get_all_tags should be called AFTER get_latest_tag (not before)
        # Verify call order: get_latest_tag first, then get_all_tags
        calls = [c[0] for c in mock_client.method_calls]
        latest_idx = next(i for i, c in enumerate(calls) if c == "get_latest_tag")
        all_tags_idx = next(i for i, c in enumerate(calls) if c == "get_all_tags")
        assert latest_idx < all_tags_idx

    @pytest.mark.asyncio
    async def test_ghcr_calls_get_all_tags_first(self, mock_db, rate_limiter):
        """GHCR should call get_all_tags first to populate TagCache."""
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="1.0.1")
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.get_all_tags = AsyncMock(return_value=["1.0.0", "1.0.1"])
        mock_client.uses_tag_cache_for_latest = True  # GHCR
        mock_client._is_non_semver_tag = MagicMock(return_value=False)
        mock_client.close = AsyncMock()

        with patch(
            "app.services.tag_fetcher.RegistryClientFactory.get_client",
            return_value=mock_client,
        ):
            fetcher = TagFetcher(mock_db, rate_limiter)
            request = make_request(registry="ghcr.io")
            await fetcher.fetch_tags(request)

        # get_all_tags should be called BEFORE get_latest_tag for GHCR
        calls = [c[0] for c in mock_client.method_calls]
        all_tags_idx = next(i for i, c in enumerate(calls) if c == "get_all_tags")
        latest_idx = next(i for i, c in enumerate(calls) if c == "get_latest_tag")
        assert all_tags_idx < latest_idx

    @pytest.mark.asyncio
    async def test_non_semver_skips_get_all_tags(self, mock_db, rate_limiter):
        """Non-semver tags should skip get_all_tags entirely."""
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.get_all_tags = AsyncMock(return_value=[])
        mock_client.get_tag_metadata = AsyncMock(return_value={"digest": "sha256:abc"})
        mock_client.uses_tag_cache_for_latest = True  # Would normally call first
        mock_client._is_non_semver_tag = MagicMock(return_value=True)
        mock_client.close = AsyncMock()

        with patch(
            "app.services.tag_fetcher.RegistryClientFactory.get_client",
            return_value=mock_client,
        ):
            fetcher = TagFetcher(mock_db, rate_limiter)
            request = make_request(current_tag="latest")
            await fetcher.fetch_tags(request)

        # get_all_tags should NOT be called for non-semver tags
        mock_client.get_all_tags.assert_not_called()
