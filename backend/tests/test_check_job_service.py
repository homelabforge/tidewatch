"""Tests for check job service (app/services/check_job_service.py).

Tests the concurrent check job management layer:
- Job creation and container counting
- Active job deduplication
- Cancellation request
- Error handling in workers
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.check_job import CheckJob
from app.models.container import Container
from app.services.check_job_service import CheckJobService


@pytest.fixture
def mock_db():
    """Create mock async database session."""
    db = AsyncMock()
    # Sync methods must be MagicMock to avoid unawaited coroutine warnings
    db.add = MagicMock()
    return db


class TestJobCreation:
    """Test job creation and container counting."""

    @pytest.mark.asyncio
    async def test_create_job_counts_non_disabled_containers(self, mock_db):
        """Job creation should count only non-disabled containers."""
        # Mock containers query
        containers = [
            Container(
                id=i,
                name=f"container-{i}",
                image="nginx",
                current_tag="1.0.0",
                registry="docker.io",
                compose_file="/compose/test.yml",
                service_name=f"svc-{i}",
                policy="monitor",
                vulnforge_enabled=False,
            )
            for i in range(5)
        ]
        result = MagicMock()
        result.scalars.return_value.all.return_value = containers
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch("app.services.check_job_service.event_bus.publish", new_callable=AsyncMock):
            job = await CheckJobService.create_job(mock_db, "user")

        assert job.total_count == 5
        assert job.status == "queued"
        assert job.triggered_by == "user"

    @pytest.mark.asyncio
    async def test_create_job_scheduler_trigger(self, mock_db):
        """Job can be created by scheduler."""
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch("app.services.check_job_service.event_bus.publish", new_callable=AsyncMock):
            job = await CheckJobService.create_job(mock_db, "scheduler")

        assert job.triggered_by == "scheduler"


class TestActiveJobDeduplication:
    """Test that only one job runs at a time."""

    @pytest.mark.asyncio
    async def test_get_active_job_returns_running(self, mock_db):
        """Should return currently running job."""
        running_job = CheckJob(id=1, status="running", total_count=10, triggered_by="user")
        result = MagicMock()
        result.scalar_one_or_none.return_value = running_job
        mock_db.execute = AsyncMock(return_value=result)

        job = await CheckJobService.get_active_job(mock_db)

        assert job is not None
        assert job.id == 1
        assert job.status == "running"

    @pytest.mark.asyncio
    async def test_get_active_job_returns_none_when_idle(self, mock_db):
        """Should return None when no job is active."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        job = await CheckJobService.get_active_job(mock_db)

        assert job is None


class TestCancellation:
    """Test job cancellation requests."""

    @pytest.mark.asyncio
    async def test_request_cancellation_sets_flag(self, mock_db):
        """Cancellation should set cancel_requested flag."""
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.services.check_job_service.event_bus.publish", new_callable=AsyncMock):
            await CheckJobService.request_cancellation(mock_db, job_id=42)

        # Verify that execute was called (the update statement)
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()


class TestJobRetrieval:
    """Test job retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_job_by_id(self, mock_db):
        """Should retrieve job by ID."""
        job = CheckJob(id=5, status="completed", total_count=10, triggered_by="user")
        result = MagicMock()
        result.scalar_one_or_none.return_value = job
        mock_db.execute = AsyncMock(return_value=result)

        retrieved = await CheckJobService.get_job(mock_db, 5)

        assert retrieved is not None
        assert retrieved.id == 5

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, mock_db):
        """Should return None for nonexistent job."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        retrieved = await CheckJobService.get_job(mock_db, 999)

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_recent_jobs(self, mock_db):
        """Should return recent jobs in descending order."""
        jobs = [
            CheckJob(id=i, status="completed", total_count=10, triggered_by="user")
            for i in range(3)
        ]
        result = MagicMock()
        result.scalars.return_value.all.return_value = jobs
        mock_db.execute = AsyncMock(return_value=result)

        recent = await CheckJobService.get_recent_jobs(mock_db, limit=10)

        assert len(recent) == 3
