"""Tests for supply chain baseline builder."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.supply_chain_baseline import SupplyChainBaseline
from app.services.supply_chain_baseline_builder import BaselineBuilder


class TestBaselineBuilder:
    @pytest.mark.asyncio
    async def test_get_baseline_empty(self, db):
        result = await BaselineBuilder.get_baseline(db, "dockerhub", "nginx", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_advance_creates_new_baseline(self, db):
        await BaselineBuilder.advance_baseline(
            db, "dockerhub", "nginx", None, "1.25.0", "sha256:abc123", 100_000_000
        )
        await db.commit()

        baseline = await BaselineBuilder.get_baseline(db, "dockerhub", "nginx", None)
        assert baseline is not None
        assert baseline.last_trusted_tag == "1.25.0"
        assert baseline.last_trusted_digest == "sha256:abc123"
        assert baseline.last_trusted_size_bytes == 100_000_000
        assert baseline.sample_count == 1

    @pytest.mark.asyncio
    async def test_advance_updates_existing_baseline(self, db):
        # Create initial
        await BaselineBuilder.advance_baseline(
            db, "dockerhub", "nginx", None, "1.25.0", "sha256:abc", 100_000_000
        )
        await db.commit()

        # Advance
        await BaselineBuilder.advance_baseline(
            db, "dockerhub", "nginx", None, "1.26.0", "sha256:def", 110_000_000
        )
        await db.commit()

        baseline = await BaselineBuilder.get_baseline(db, "dockerhub", "nginx", None)
        assert baseline.last_trusted_tag == "1.26.0"
        assert baseline.last_trusted_digest == "sha256:def"
        assert baseline.last_trusted_size_bytes == 110_000_000
        assert baseline.sample_count == 2

    @pytest.mark.asyncio
    async def test_baselines_keyed_by_registry_image_track(self, db):
        await BaselineBuilder.advance_baseline(
            db, "dockerhub", "nginx", None, "1.25.0", "sha256:a", 100_000_000
        )
        await BaselineBuilder.advance_baseline(
            db, "ghcr", "nginx", None, "1.25.0", "sha256:b", 100_000_000
        )
        await BaselineBuilder.advance_baseline(
            db, "dockerhub", "nginx", "calver", "2025.1", "sha256:c", 100_000_000
        )
        await db.commit()

        result = await db.execute(select(SupplyChainBaseline))
        baselines = result.scalars().all()
        assert len(baselines) == 3

    @pytest.mark.asyncio
    async def test_bootstrap_from_docker_inspect(self, db):
        mock_result = {
            "RepoDigests": ["nginx@sha256:inspected_digest"],
            "Size": 50_000_000,
        }

        with patch(
            "app.services.supply_chain_baseline_builder._docker_image_inspect",
            return_value=mock_result,
        ):
            await BaselineBuilder.bootstrap_from_current(db, "dockerhub", "nginx", None, "1.25.0")
            await db.commit()

        baseline = await BaselineBuilder.get_baseline(db, "dockerhub", "nginx", None)
        assert baseline is not None
        assert baseline.last_trusted_digest == "sha256:inspected_digest"
        assert baseline.last_trusted_size_bytes == 50_000_000

    @pytest.mark.asyncio
    async def test_bootstrap_falls_back_to_registry(self, db):
        mock_client = AsyncMock()
        mock_client.get_tag_metadata.return_value = {
            "digest": "sha256:registry_digest",
            "full_size": 60_000_000,
        }
        mock_client.close = AsyncMock()

        with (
            patch(
                "app.services.supply_chain_baseline_builder._docker_image_inspect",
                return_value=None,
            ),
            patch(
                "app.services.supply_chain_baseline_builder.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
        ):
            await BaselineBuilder.bootstrap_from_current(db, "dockerhub", "nginx", None, "1.25.0")
            await db.commit()

        baseline = await BaselineBuilder.get_baseline(db, "dockerhub", "nginx", None)
        assert baseline is not None
        assert baseline.last_trusted_digest == "sha256:registry_digest"

    @pytest.mark.asyncio
    async def test_bootstrap_no_digest_available(self, db):
        with (
            patch(
                "app.services.supply_chain_baseline_builder._docker_image_inspect",
                return_value=None,
            ),
            patch(
                "app.services.supply_chain_baseline_builder.RegistryClientFactory.get_client",
                side_effect=Exception("registry down"),
            ),
        ):
            await BaselineBuilder.bootstrap_from_current(db, "dockerhub", "nginx", None, "1.25.0")
            await db.commit()

        # No baseline should be created
        baseline = await BaselineBuilder.get_baseline(db, "dockerhub", "nginx", None)
        assert baseline is None
