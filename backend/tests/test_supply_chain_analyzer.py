"""Tests for supply chain analyzer."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.models.release_corroboration_cache import ReleaseCorroborationCache
from app.services.supply_chain_analyzer import (
    AnomalySignal,
    DigestMutationError,
    ReleaseStatus,
    SupplyChainAnalyzer,
    check_release_exists,
    resolve_supply_chain_enabled,
    signal_to_dict,
)

# --- check_release_exists ---


class TestCheckReleaseExists:
    @pytest.mark.asyncio
    async def test_exists_200(self):
        with patch("app.services.supply_chain_analyzer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.get.return_value = mock_response

            result = await check_release_exists("github:owner/repo", "v1.0.0", "token123")
            assert result == ReleaseStatus.EXISTS

    @pytest.mark.asyncio
    async def test_exists_200_empty_body(self):
        with patch("app.services.supply_chain_analyzer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {}
            mock_client.get.return_value = mock_response

            result = await check_release_exists("owner/repo", "1.0.0", "token123")
            assert result == ReleaseStatus.EXISTS

    @pytest.mark.asyncio
    async def test_missing_404_all_variants(self):
        with patch("app.services.supply_chain_analyzer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_client.get.return_value = mock_response

            result = await check_release_exists("owner/repo", "1.0.0", "token123")
            assert result == ReleaseStatus.MISSING

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        with patch("app.services.supply_chain_analyzer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get.side_effect = httpx.TimeoutException("timeout")

            result = await check_release_exists("owner/repo", "1.0.0", "token123")
            assert result == ReleaseStatus.ERROR

    @pytest.mark.asyncio
    async def test_no_source(self):
        result = await check_release_exists("", "1.0.0", "token123")
        assert result == ReleaseStatus.NO_SOURCE

    @pytest.mark.asyncio
    async def test_github_prefix_stripped(self):
        with patch("app.services.supply_chain_analyzer.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.get.return_value = mock_response

            await check_release_exists("github:owner/repo", "1.0.0", None)
            # Should have tried owner/repo (without github: prefix)
            call_url = mock_client.get.call_args[0][0]
            assert "owner/repo" in call_url
            assert "github:" not in call_url


# --- resolve_supply_chain_enabled ---


class TestResolveEnabled:
    def test_container_true_overrides_global_false(self):
        assert resolve_supply_chain_enabled(True, False) is True

    def test_container_false_overrides_global_true(self):
        assert resolve_supply_chain_enabled(False, True) is False

    def test_none_inherits_global_true(self):
        assert resolve_supply_chain_enabled(None, True) is True

    def test_none_inherits_global_false(self):
        assert resolve_supply_chain_enabled(None, False) is False


# --- signal_to_dict ---


class TestSignalToDict:
    def test_converts_correctly(self):
        signal = AnomalySignal("test", 25, "detail", "enrichment")
        d = signal_to_dict(signal)
        assert d == {"name": "test", "score": 25, "detail": "detail", "tier": "enrichment"}


# --- SupplyChainAnalyzer ---


class TestSupplyChainAnalyzer:
    @pytest.mark.asyncio
    async def test_capture_candidate_metadata(self, db):
        analyzer = SupplyChainAnalyzer()
        mock_client = AsyncMock()
        mock_client.get_tag_metadata.return_value = {
            "digest": "sha256:abc123",
            "full_size": 12345678,
        }
        mock_client.close = AsyncMock()

        with patch(
            "app.services.supply_chain_analyzer.RegistryClientFactory.get_client",
            return_value=mock_client,
        ):
            digest, size = await analyzer.capture_candidate_metadata(
                db, "dockerhub", "nginx", "1.25.0"
            )
            assert digest == "sha256:abc123"
            assert size == 12345678

    @pytest.mark.asyncio
    async def test_capture_metadata_ghcr_no_size(self, db):
        analyzer = SupplyChainAnalyzer()
        mock_client = AsyncMock()
        mock_client.get_tag_metadata.return_value = {
            "digest": "sha256:def456",
        }
        mock_client.close = AsyncMock()

        with patch(
            "app.services.supply_chain_analyzer.RegistryClientFactory.get_client",
            return_value=mock_client,
        ):
            digest, size = await analyzer.capture_candidate_metadata(db, "ghcr", "org/app", "2.0.0")
            assert digest == "sha256:def456"
            assert size is None

    @pytest.mark.asyncio
    async def test_analyze_image_no_baseline(self, db):
        analyzer = SupplyChainAnalyzer()
        result = await analyzer.analyze_image(db, "dockerhub", "nginx", None, 50000000)
        assert result.score == 0
        assert result.flags == []

    @pytest.mark.asyncio
    async def test_analyze_image_size_anomaly(self, db):
        """Size change >50% triggers anomaly."""
        from app.models.supply_chain_baseline import SupplyChainBaseline

        # Create baseline
        baseline = SupplyChainBaseline(
            registry="dockerhub",
            image="nginx",
            version_track=None,
            last_trusted_tag="1.24.0",
            last_trusted_digest="sha256:old",
            last_trusted_size_bytes=100_000_000,
            sample_count=3,
        )
        db.add(baseline)
        await db.flush()

        analyzer = SupplyChainAnalyzer()
        # 200MB vs 100MB baseline = 100% change
        result = await analyzer.analyze_image(db, "dockerhub", "nginx", None, 200_000_000)
        assert result.score == 25
        assert len(result.flags) == 1
        assert result.flags[0].name == "size_anomaly"

    @pytest.mark.asyncio
    async def test_analyze_image_normal_size(self, db):
        """Size change <50% does not trigger anomaly."""
        from app.models.supply_chain_baseline import SupplyChainBaseline

        baseline = SupplyChainBaseline(
            registry="dockerhub",
            image="nginx",
            version_track=None,
            last_trusted_tag="1.24.0",
            last_trusted_digest="sha256:old",
            last_trusted_size_bytes=100_000_000,
            sample_count=3,
        )
        db.add(baseline)
        await db.flush()

        analyzer = SupplyChainAnalyzer()
        # 120MB vs 100MB baseline = 20% change
        result = await analyzer.analyze_image(db, "dockerhub", "nginx", None, 120_000_000)
        assert result.score == 0
        assert result.flags == []

    @pytest.mark.asyncio
    async def test_analyze_container_no_release_source(self, db):
        analyzer = SupplyChainAnalyzer()
        result = await analyzer.analyze_container(db, None, "1.0.0")
        assert result.held is False
        assert result.flags == []

    @pytest.mark.asyncio
    async def test_analyze_container_missing_release(self, db):
        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.MISSING,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            result = await analyzer.analyze_container(db, "github:owner/repo", "1.0.0")
            assert result.held is True
            assert result.flags[0].name == "missing_release"

    @pytest.mark.asyncio
    async def test_analyze_container_github_error(self, db):
        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.ERROR,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            result = await analyzer.analyze_container(db, "github:owner/repo", "1.0.0")
            assert result.held is True
            assert result.flags[0].name == "release_check_failed"

    @pytest.mark.asyncio
    async def test_corroboration_cache(self, db):
        """Second call for same key hits in-memory cache."""
        analyzer = SupplyChainAnalyzer()
        call_count = 0

        async def mock_check(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ReleaseStatus.EXISTS

        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                side_effect=mock_check,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            await analyzer.analyze_container(db, "github:owner/repo", "1.0.0")
            await analyzer.analyze_container(db, "github:owner/repo", "1.0.0")
            assert call_count == 1  # Only one actual API call


# --- Persistent Corroboration Cache (Phase 1) ---


class TestPersistentCache:
    @pytest.mark.asyncio
    async def test_persistent_cache_hit(self, db):
        """Recent EXISTS row in DB skips GitHub API call."""
        # Seed a fresh EXISTS row
        cache_row = ReleaseCorroborationCache(
            release_source="github:owner/repo",
            tag="1.0.0",
            status="exists",
            checked_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db.add(cache_row)
        await db.commit()

        analyzer = SupplyChainAnalyzer()
        with patch(
            "app.services.supply_chain_analyzer.check_release_exists",
        ) as mock_check:
            result = await analyzer.analyze_container(db, "github:owner/repo", "1.0.0")
            assert result.held is False
            mock_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_persistent_cache_stale(self, db):
        """Old EXISTS row triggers re-check and row update."""
        # Seed a stale row (3 hours old, TTL is 2h default)
        cache_row = ReleaseCorroborationCache(
            release_source="github:owner/repo",
            tag="2.0.0",
            status="exists",
            checked_at=datetime.now(UTC) - timedelta(hours=3),
        )
        db.add(cache_row)
        await db.commit()

        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.EXISTS,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            result = await analyzer.analyze_container(db, "github:owner/repo", "2.0.0")
            assert result.held is False

        # Expire ORM cache — raw SQL upsert bypasses identity map
        db.expire_all()
        row = (
            await db.execute(
                select(ReleaseCorroborationCache).where(
                    ReleaseCorroborationCache.release_source == "github:owner/repo",
                    ReleaseCorroborationCache.tag == "2.0.0",
                )
            )
        ).scalar_one()
        assert (datetime.now(UTC) - row.checked_at).total_seconds() < 10

    @pytest.mark.asyncio
    async def test_persistent_cache_miss_not_written(self, db):
        """MISSING result is not persisted to DB."""
        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.MISSING,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            await analyzer.analyze_container(db, "github:owner/repo", "3.0.0")

        row = (
            await db.execute(
                select(ReleaseCorroborationCache).where(
                    ReleaseCorroborationCache.release_source == "github:owner/repo",
                    ReleaseCorroborationCache.tag == "3.0.0",
                )
            )
        ).scalar_one_or_none()
        assert row is None

    @pytest.mark.asyncio
    async def test_persistent_cache_error_not_written(self, db):
        """ERROR result is not persisted to DB."""
        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.ERROR,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            await analyzer.analyze_container(db, "github:owner/repo", "4.0.0")

        row = (
            await db.execute(
                select(ReleaseCorroborationCache).where(
                    ReleaseCorroborationCache.release_source == "github:owner/repo",
                    ReleaseCorroborationCache.tag == "4.0.0",
                )
            )
        ).scalar_one_or_none()
        assert row is None

    @pytest.mark.asyncio
    async def test_persistent_cache_upsert_on_conflict(self, db):
        """Second EXISTS for same key updates checked_at, not inserts duplicate."""
        old_time = datetime.now(UTC) - timedelta(hours=3)
        cache_row = ReleaseCorroborationCache(
            release_source="github:owner/repo",
            tag="5.0.0",
            status="exists",
            checked_at=old_time,
        )
        db.add(cache_row)
        await db.commit()

        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.EXISTS,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            await analyzer.analyze_container(db, "github:owner/repo", "5.0.0")

        # Expire ORM cache — raw SQL upsert bypasses identity map
        db.expire_all()
        rows = (
            (
                await db.execute(
                    select(ReleaseCorroborationCache).where(
                        ReleaseCorroborationCache.release_source == "github:owner/repo",
                        ReleaseCorroborationCache.tag == "5.0.0",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].checked_at > old_time


# --- GitHub Outage Grace Period (Phase 2) ---


class TestGracePeriod:
    @pytest.mark.asyncio
    async def test_github_error_with_grace_period(self, db):
        """Recent EXISTS for same source → held=True, flag is github_grace_period."""
        # Seed a recent EXISTS for this source (different tag is fine)
        cache_row = ReleaseCorroborationCache(
            release_source="github:owner/repo",
            tag="0.9.0",
            status="exists",
            checked_at=datetime.now(UTC) - timedelta(hours=2),
        )
        db.add(cache_row)
        await db.commit()

        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.ERROR,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            result = await analyzer.analyze_container(db, "github:owner/repo", "1.0.0")
            assert result.held is True
            assert result.flags[0].name == "github_grace_period"
            assert "verified" in result.flags[0].detail
            assert "manual approval required" in result.flags[0].detail

    @pytest.mark.asyncio
    async def test_github_error_no_grace_data(self, db):
        """No prior checks → held=True, flag is release_check_failed."""
        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.ERROR,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            result = await analyzer.analyze_container(db, "github:fresh/repo", "1.0.0")
            assert result.held is True
            assert result.flags[0].name == "release_check_failed"

    @pytest.mark.asyncio
    async def test_github_error_grace_expired(self, db):
        """Old EXISTS beyond window → held=True, flag is release_check_failed."""
        # Seed an old row (30 hours ago, grace is 24h)
        cache_row = ReleaseCorroborationCache(
            release_source="github:owner/old",
            tag="0.5.0",
            status="exists",
            checked_at=datetime.now(UTC) - timedelta(hours=30),
        )
        db.add(cache_row)
        await db.commit()

        analyzer = SupplyChainAnalyzer()
        with (
            patch(
                "app.services.supply_chain_analyzer.check_release_exists",
                return_value=ReleaseStatus.ERROR,
            ),
            patch(
                "app.services.supply_chain_analyzer.SettingsService.get",
                return_value="token123",
            ),
        ):
            result = await analyzer.analyze_container(db, "github:owner/old", "1.0.0")
            assert result.held is True
            assert result.flags[0].name == "release_check_failed"


# --- Per-Key Task Map (Phase 3) ---


class TestTaskMap:
    @pytest.mark.asyncio
    async def test_concurrent_different_keys_parallel(self, db):
        """Two different keys run concurrently, not serialized."""
        import time

        call_times: list[float] = []

        async def slow_fetch_and_cache(_db, _source, _tag):
            call_times.append(time.monotonic())
            await asyncio.sleep(0.1)
            return ReleaseStatus.EXISTS

        analyzer = SupplyChainAnalyzer()
        with patch.object(
            SupplyChainAnalyzer, "_fetch_and_cache", side_effect=slow_fetch_and_cache
        ):
            start = time.monotonic()
            await asyncio.gather(
                analyzer.analyze_container(db, "github:owner/repo-a", "1.0.0"),
                analyzer.analyze_container(db, "github:owner/repo-b", "1.0.0"),
            )
            elapsed = time.monotonic() - start

        # Both should complete in ~0.1s (parallel), not ~0.2s (serial)
        assert elapsed < 0.18, f"Expected parallel execution but took {elapsed:.3f}s"
        assert len(call_times) == 2

    @pytest.mark.asyncio
    async def test_concurrent_same_key_deduplicates(self, db):
        """Same key from two callers → single API call."""
        call_count = 0

        async def slow_fetch_and_cache(_db, _source, _tag):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return ReleaseStatus.EXISTS

        analyzer = SupplyChainAnalyzer()
        with patch.object(
            SupplyChainAnalyzer, "_fetch_and_cache", side_effect=slow_fetch_and_cache
        ):
            results = await asyncio.gather(
                analyzer.analyze_container(db, "github:owner/repo", "1.0.0"),
                analyzer.analyze_container(db, "github:owner/repo", "1.0.0"),
            )

        assert call_count == 1
        assert all(r.held is False for r in results)

    @pytest.mark.asyncio
    async def test_failed_task_evicted_and_retried(self, db):
        """First call raises, second call creates a new task and succeeds."""
        attempt = 0

        async def flaky_fetch_and_cache(_db, _source, _tag):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise RuntimeError("Transient failure")
            return ReleaseStatus.EXISTS

        analyzer = SupplyChainAnalyzer()
        with patch.object(
            SupplyChainAnalyzer, "_fetch_and_cache", side_effect=flaky_fetch_and_cache
        ):
            with pytest.raises(RuntimeError, match="Transient failure"):
                await analyzer.analyze_container(db, "github:owner/flaky", "1.0.0")

            # Second call should retry and succeed
            result = await analyzer.analyze_container(db, "github:owner/flaky", "1.0.0")
            assert result.held is False

        assert attempt == 2

    @pytest.mark.asyncio
    async def test_failed_task_eviction_identity_check(self, db):
        """Eviction doesn't remove a replacement task (identity check)."""
        analyzer = SupplyChainAnalyzer()
        cache_key = ("github:owner/identity", "1.0.0")

        # Manually inject a different task into inflight to simulate race
        async def sentinel_coro() -> ReleaseStatus:
            await asyncio.sleep(10)
            return ReleaseStatus.EXISTS

        sentinel_task = asyncio.create_task(sentinel_coro())
        analyzer._inflight[cache_key] = sentinel_task

        # Create and fail a task with the same key but different identity
        failed_task = asyncio.create_task(asyncio.sleep(0))
        await failed_task  # let it complete

        # Simulate eviction with identity check — should NOT remove sentinel
        async with analyzer._lock:
            if analyzer._inflight.get(cache_key) is failed_task:
                del analyzer._inflight[cache_key]

        # Sentinel should still be there
        assert analyzer._inflight.get(cache_key) is sentinel_task

        # Cleanup
        sentinel_task.cancel()
        try:
            await sentinel_task
        except asyncio.CancelledError:
            pass


# --- DigestMutationError ---


class TestDigestMutationError:
    def test_is_exception(self):
        err = DigestMutationError("digest changed")
        assert isinstance(err, Exception)
        assert str(err) == "digest changed"
