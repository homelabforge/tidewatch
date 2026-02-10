"""Integration tests for VulnForge scan workflow.

Tests the full PendingScanJob lifecycle:
- pending → triggered → polling → completed
- pending → triggered → polling → failed
- Crash recovery (restart with in-flight jobs)
- CVE delta writer
- VulnForge client name-based container lookup
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.history import UpdateHistory
from app.models.pending_scan_job import PendingScanJob

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_pending_job(db, update, **kwargs):
    """Create a PendingScanJob linked to an Update."""
    defaults = {
        "container_name": update.container_name,
        "update_id": update.id,
        "status": "pending",
    }
    defaults.update(kwargs)
    job = PendingScanJob(**defaults)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


def _make_mock_session_ctx(db):
    """Build a mock async context manager that returns the test db session."""

    class _MockSessionCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    return _MockSessionCtx()


def _mock_vulnforge_client(**method_overrides):
    """Build a mock VulnForgeClient with sensible defaults."""
    client = AsyncMock()
    client.trigger_scan_by_name = AsyncMock(return_value={"job_ids": [42], "queued": 1})
    client.get_scan_job_status = AsyncMock(return_value={"status": "completed", "scan_id": 100})
    client.get_cve_delta = AsyncMock(
        return_value={
            "scans": [
                {
                    "cves_fixed": ["CVE-2024-0001", "CVE-2024-0002"],
                    "cves_introduced": [],
                    "total_vulns": 5,
                }
            ]
        }
    )
    client.close = AsyncMock()

    for method, return_value in method_overrides.items():
        getattr(client, method).return_value = return_value

    return client


# ---------------------------------------------------------------------------
# PendingScanJob model tests
# ---------------------------------------------------------------------------


class TestPendingScanJobModel:
    """Unit tests for the PendingScanJob model."""

    async def test_create_pending_job(self, db, make_update):
        """Test creating a PendingScanJob and linking to Update."""
        update = make_update(container_id=1, container_name="nginx")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = PendingScanJob(
            container_name="nginx",
            update_id=update.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        assert job.id is not None
        assert job.status == "pending"
        assert job.poll_count == 0
        assert job.max_polls == 12
        assert job.is_active is True
        assert job.polls_exhausted is False

    async def test_polls_exhausted(self, db, make_update):
        """Test polls_exhausted property."""
        update = make_update(container_id=1, container_name="nginx")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = PendingScanJob(
            container_name="nginx",
            update_id=update.id,
            poll_count=12,
            max_polls=12,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        assert job.polls_exhausted is True

    async def test_is_active_states(self, db, make_update):
        """Test is_active for all statuses."""
        update = make_update(container_id=1, container_name="nginx")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        for status, expected in [
            ("pending", True),
            ("triggered", True),
            ("polling", True),
            ("completed", False),
            ("failed", False),
        ]:
            job = PendingScanJob(
                container_name="nginx",
                update_id=update.id,
                status=status,
            )
            db.add(job)
            await db.commit()
            assert job.is_active is expected


# ---------------------------------------------------------------------------
# CVE delta writer tests
# ---------------------------------------------------------------------------


class TestCveDeltaWriter:
    """Tests for the shared CVE delta writer."""

    async def test_write_cve_delta_updates_record(self, db, make_update):
        """Test that CVE delta data is written to Update and UpdateHistory."""
        from app.services.vulnforge_cve_writer import write_cve_delta

        update = make_update(container_id=1, container_name="nginx")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Create a matching UpdateHistory
        history = UpdateHistory(
            container_id=1,
            update_id=update.id,
            container_name="nginx",
            from_tag="1.0.0",
            to_tag="1.1.0",
            status="applied",
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        result = await write_cve_delta(
            db=db,
            update_id=update.id,
            container_name="nginx",
            cves_fixed=["CVE-2024-0001", "CVE-2024-0002"],
            cves_introduced=["CVE-2024-0003"],
            total_vulns=10,
            scan_id=42,
        )
        await db.commit()

        assert result is True

        # Verify Update record
        await db.refresh(update)
        assert update.cves_fixed == ["CVE-2024-0001", "CVE-2024-0002"]
        assert update.new_vulns == 10
        assert update.vuln_delta == -1  # 1 introduced - 2 fixed

        # Verify UpdateHistory
        await db.refresh(history)
        assert history.cves_fixed == ["CVE-2024-0001", "CVE-2024-0002"]

    async def test_write_cve_delta_missing_update(self, db):
        """Test that missing Update record returns False."""
        from app.services.vulnforge_cve_writer import write_cve_delta

        result = await write_cve_delta(
            db=db,
            update_id=99999,
            container_name="nonexistent",
            cves_fixed=[],
            cves_introduced=[],
            total_vulns=0,
        )

        assert result is False

    async def test_write_cve_delta_no_history(self, db, make_update):
        """Test writing CVE data when no UpdateHistory exists (still succeeds)."""
        from app.services.vulnforge_cve_writer import write_cve_delta

        update = make_update(container_id=1, container_name="traefik")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        result = await write_cve_delta(
            db=db,
            update_id=update.id,
            container_name="traefik",
            cves_fixed=["CVE-2024-1234"],
            cves_introduced=[],
            total_vulns=3,
        )
        await db.commit()

        assert result is True
        await db.refresh(update)
        assert update.cves_fixed == ["CVE-2024-1234"]
        assert update.new_vulns == 3


# ---------------------------------------------------------------------------
# Scan worker tests
# ---------------------------------------------------------------------------


class TestVulnForgeScanWorker:
    """Integration tests for the APScheduler-driven scan worker."""

    async def _patch_session_and_client(self, db, mock_client):
        """Helper to patch AsyncSessionLocal and create_vulnforge_client."""
        return (
            patch(
                "app.services.vulnforge_scan_worker.AsyncSessionLocal",
                return_value=_make_mock_session_ctx(db),
            ),
            patch(
                "app.services.vulnforge_scan_worker._get_vulnforge_client",
                return_value=mock_client,
            ),
        )

    async def test_full_lifecycle_pending_to_completed(self, db, make_update):
        """Test complete lifecycle: pending → triggered → polling → completed."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="nginx")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Create a matching UpdateHistory for CVE backfill
        history = UpdateHistory(
            container_id=1,
            update_id=update.id,
            container_name="nginx",
            from_tag="1.0.0",
            to_tag="1.1.0",
            status="applied",
        )
        db.add(history)
        await db.commit()

        job = await _create_pending_job(db, update)

        mock_client = _mock_vulnforge_client()

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            # Cycle 1: pending → triggered
            await process_pending_scan_jobs()
            await db.refresh(job)
            assert job.status == "triggered"
            assert job.vulnforge_job_id == 42

            # Cycle 2: triggered → polling → completed (with CVE delta)
            await process_pending_scan_jobs()
            await db.refresh(job)
            assert job.status == "completed"
            assert job.vulnforge_scan_id == 100
            assert job.completed_at is not None

        # Verify CVE data was written
        await db.refresh(update)
        assert update.cves_fixed == ["CVE-2024-0001", "CVE-2024-0002"]
        assert update.new_vulns == 5

    async def test_scan_trigger_failure_retries(self, db, make_update):
        """Test that a single trigger failure retries instead of hard-failing."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="postgres")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(db, update)

        mock_client = _mock_vulnforge_client(trigger_scan_by_name=None)

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        # No longer hard-fails — retries with incremented attempt count
        assert job.status == "pending"
        assert job.trigger_attempt_count == 1
        assert job.last_trigger_attempt_at is not None

    async def test_poll_returns_failed_status(self, db, make_update):
        """Test that VulnForge reporting 'failed' marks the job failed."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="redis")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(
            db,
            update,
            status="polling",
            vulnforge_job_id=42,
            last_polled_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        mock_client = _mock_vulnforge_client(
            get_scan_job_status={"status": "failed", "error_message": "scan timeout"}
        )

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        assert job.status == "failed"
        assert "scan timeout" in (job.error_message or "")

    async def test_poll_exhaustion(self, db, make_update):
        """Test that exhausting poll attempts marks job as failed."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="sonarr")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(
            db,
            update,
            status="polling",
            vulnforge_job_id=42,
            poll_count=12,
            max_polls=12,
            last_polled_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        mock_client = _mock_vulnforge_client()

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        assert job.status == "failed"
        assert "exhausted" in (job.error_message or "").lower()

    async def test_vulnforge_disabled_marks_failed(self, db, make_update):
        """Test that disabled VulnForge marks pending jobs as failed."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="nginx")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(db, update)

        session_patch, client_patch = await self._patch_session_and_client(db, None)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        assert job.status == "failed"
        assert "disabled" in (job.error_message or "").lower()

    async def test_no_cve_delta_still_completes(self, db, make_update):
        """Test that empty CVE delta still marks the job as completed."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="grafana")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(
            db,
            update,
            status="polling",
            vulnforge_job_id=42,
            last_polled_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        # get_cve_delta returns empty
        mock_client = _mock_vulnforge_client(get_cve_delta={"scans": []})

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        assert job.status == "completed"

    async def test_respects_poll_interval(self, db, make_update):
        """Test that polling is skipped when last_polled_at is too recent."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="caddy")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(
            db,
            update,
            status="polling",
            vulnforge_job_id=42,
            last_polled_at=datetime.now(UTC),  # Just polled
        )

        mock_client = _mock_vulnforge_client()

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        # Should still be polling — interval not yet reached
        assert job.status == "polling"
        mock_client.get_scan_job_status.assert_not_called()


# ---------------------------------------------------------------------------
# Crash recovery tests
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    """Tests for interrupted job recovery at startup."""

    async def test_recover_triggered_with_job_id(self, db, make_update):
        """Triggered job with vulnforge_job_id → resumes as polling."""
        from app.services.vulnforge_scan_worker import recover_interrupted_jobs

        update = make_update(container_id=1, container_name="nginx")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(db, update, status="triggered", vulnforge_job_id=42)

        with patch(
            "app.services.vulnforge_scan_worker.AsyncSessionLocal",
            return_value=_make_mock_session_ctx(db),
        ):
            await recover_interrupted_jobs()

        await db.refresh(job)
        assert job.status == "polling"

    async def test_recover_triggered_without_job_id(self, db, make_update):
        """Triggered job without vulnforge_job_id → resets to pending."""
        from app.services.vulnforge_scan_worker import recover_interrupted_jobs

        update = make_update(container_id=1, container_name="postgres")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(db, update, status="triggered", vulnforge_job_id=None)

        with patch(
            "app.services.vulnforge_scan_worker.AsyncSessionLocal",
            return_value=_make_mock_session_ctx(db),
        ):
            await recover_interrupted_jobs()

        await db.refresh(job)
        assert job.status == "pending"

    async def test_recover_polling_resumes(self, db, make_update):
        """Polling job → resumes as polling."""
        from app.services.vulnforge_scan_worker import recover_interrupted_jobs

        update = make_update(container_id=1, container_name="traefik")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(
            db,
            update,
            status="polling",
            vulnforge_job_id=99,
            poll_count=3,
        )

        with patch(
            "app.services.vulnforge_scan_worker.AsyncSessionLocal",
            return_value=_make_mock_session_ctx(db),
        ):
            await recover_interrupted_jobs()

        await db.refresh(job)
        assert job.status == "polling"
        assert job.poll_count == 3  # Preserved

    async def test_completed_jobs_not_recovered(self, db, make_update):
        """Completed/failed jobs should not be touched by recovery."""
        from app.services.vulnforge_scan_worker import recover_interrupted_jobs

        update = make_update(container_id=1, container_name="redis")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        completed = await _create_pending_job(db, update, status="completed")
        failed = await _create_pending_job(db, update, status="failed")

        with patch(
            "app.services.vulnforge_scan_worker.AsyncSessionLocal",
            return_value=_make_mock_session_ctx(db),
        ):
            await recover_interrupted_jobs()

        await db.refresh(completed)
        await db.refresh(failed)
        assert completed.status == "completed"
        assert failed.status == "failed"


# ---------------------------------------------------------------------------
# VulnForge client name-based lookup tests
# ---------------------------------------------------------------------------


class TestVulnForgeClientNameLookup:
    """Tests for get_container_id_by_name with O(1) + fallback."""

    async def test_by_name_direct_hit(self):
        """Test O(1) by-name endpoint returns container ID."""
        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 7, "name": "nginx"}

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(return_value=mock_response)

        result = await client.get_container_id_by_name("nginx")
        assert result == 7

        # Should only call the by-name URL
        client.client.get.assert_called_once_with(
            "http://vulnforge:8787/api/v1/containers/by-name/nginx"
        )

    async def test_by_name_404_returns_none(self):
        """Test that 404 from by-name endpoint returns None without fallback."""
        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 404

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(return_value=mock_response)

        result = await client.get_container_id_by_name("nonexistent")
        assert result is None

        # Should only have called once (no fallback)
        assert client.client.get.call_count == 1

    async def test_by_name_fallback_to_list(self):
        """Test fallback to list-all when by-name returns unexpected status."""
        from app.services.vulnforge_client import VulnForgeClient

        # First call: by-name returns 500
        by_name_response = MagicMock()
        by_name_response.status_code = 500

        # Second call: list-all succeeds
        list_response = MagicMock()
        list_response.status_code = 200
        list_response.raise_for_status = MagicMock()
        list_response.json.return_value = {
            "containers": [
                {"id": 1, "name": "postgres"},
                {"id": 2, "name": "nginx"},
            ]
        }

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(side_effect=[by_name_response, list_response])

        result = await client.get_container_id_by_name("nginx")
        assert result == 2
        assert client.client.get.call_count == 2

    async def test_connection_error_returns_none(self):
        """Test that connection errors return None immediately."""
        import httpx

        from app.services.vulnforge_client import VulnForgeClient

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client.get_container_id_by_name("nginx")
        assert result is None


# ---------------------------------------------------------------------------
# VulnForge client image-based lookup tests (Phase 7)
# ---------------------------------------------------------------------------


class TestVulnForgeClientImageLookup:
    """Tests for get_containers_by_image with O(1) + fallback."""

    async def test_server_side_hit(self):
        """Test that /by-image endpoint returns matching containers."""
        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "nginx-prod", "image": "nginx", "image_tag": "latest"},
        ]

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(return_value=mock_response)

        result = await client.get_containers_by_image("nginx", "latest")
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "nginx-prod"

        # Should call /by-image with correct params
        client.client.get.assert_called_once_with(
            "http://vulnforge:8787/api/v1/containers/by-image",
            params={"image": "nginx", "tag": "latest"},
        )

    async def test_server_side_not_found_returns_empty(self):
        """Test that 404 from /by-image returns empty list (no fallback)."""
        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 404

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(return_value=mock_response)

        result = await client.get_containers_by_image("nonexistent", "latest")
        assert result == []
        assert client.client.get.call_count == 1  # No fallback

    async def test_fallback_on_405(self):
        """Test fallback to list-all when /by-image returns 405 (old VulnForge)."""
        from app.services.vulnforge_client import VulnForgeClient

        # First call: /by-image returns 405 (endpoint doesn't exist)
        by_image_response = MagicMock()
        by_image_response.status_code = 405

        # Second call: list-all succeeds
        list_response = MagicMock()
        list_response.status_code = 200
        list_response.raise_for_status = MagicMock()
        list_response.json.return_value = {
            "containers": [
                {"id": 1, "name": "nginx-prod", "image": "nginx", "image_tag": "latest"},
                {"id": 2, "name": "postgres", "image": "postgres", "image_tag": "15"},
            ]
        }

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(side_effect=[by_image_response, list_response])

        result = await client.get_containers_by_image("nginx", "latest")
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "nginx-prod"
        assert client.client.get.call_count == 2  # /by-image + /containers/

    async def test_connection_error_returns_none(self):
        """Test that connection errors return None immediately (no fallback)."""
        import httpx

        from app.services.vulnforge_client import VulnForgeClient

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client.get_containers_by_image("nginx", "latest")
        assert result is None
        assert client.client.get.call_count == 1  # No fallback on connection error

    async def test_no_tag_returns_all_tags(self):
        """Test that omitting tag returns containers with any tag."""
        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "ng-25", "image": "nginx", "image_tag": "1.25"},
            {"id": 2, "name": "ng-26", "image": "nginx", "image_tag": "1.26"},
        ]

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(return_value=mock_response)

        result = await client.get_containers_by_image("nginx")
        assert result is not None
        assert len(result) == 2

        # Should call with only image param (no tag)
        client.client.get.assert_called_once_with(
            "http://vulnforge:8787/api/v1/containers/by-image",
            params={"image": "nginx"},
        )

    async def test_multiple_matches_returned(self):
        """Test that multiple containers with same image+tag are returned."""
        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "web-1", "image": "nginx", "image_tag": "latest"},
            {"id": 2, "name": "web-2", "image": "nginx", "image_tag": "latest"},
        ]

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.get = AsyncMock(return_value=mock_response)

        result = await client.get_containers_by_image("nginx", "latest")
        assert result is not None
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Trigger retry + discovery tests (race condition fix)
# ---------------------------------------------------------------------------


class TestTriggerRetryWithDiscovery:
    """Tests for bounded retry with VulnForge container discovery.

    When TideWatch force-recreates a container during an update, VulnForge
    may not have discovered the new container yet.  The scan worker should
    retry with backoff and trigger discovery instead of hard-failing.
    """

    async def _patch_session_and_client(self, db, mock_client):
        """Helper to patch AsyncSessionLocal and create_vulnforge_client."""
        return (
            patch(
                "app.services.vulnforge_scan_worker.AsyncSessionLocal",
                return_value=_make_mock_session_ctx(db),
            ),
            patch(
                "app.services.vulnforge_scan_worker._get_vulnforge_client",
                return_value=mock_client,
            ),
        )

    async def test_first_trigger_failure_retries_instead_of_failing(self, db, make_update):
        """First trigger miss increments attempt count, stays pending."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="glances")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(db, update)
        assert job.trigger_attempt_count == 0

        # trigger_scan_by_name returns None (container not found in VulnForge)
        mock_client = _mock_vulnforge_client(trigger_scan_by_name=None)

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        # Should NOT be failed — should stay pending with incremented attempt
        assert job.status == "pending"
        assert job.trigger_attempt_count == 1
        assert job.last_trigger_attempt_at is not None

    async def test_retries_exhaust_then_fails(self, db, make_update):
        """After MAX_TRIGGER_ATTEMPTS, job is marked failed."""
        from app.services.vulnforge_scan_worker import (
            MAX_TRIGGER_ATTEMPTS,
            process_pending_scan_jobs,
        )

        update = make_update(container_id=1, container_name="glances")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Pre-set to max attempts (simulates previous retries)
        job = await _create_pending_job(
            db,
            update,
            trigger_attempt_count=MAX_TRIGGER_ATTEMPTS,
            last_trigger_attempt_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        mock_client = _mock_vulnforge_client(trigger_scan_by_name=None)

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        assert job.status == "failed"
        assert "exhausted" in (job.error_message or "").lower()
        assert str(MAX_TRIGGER_ATTEMPTS) in (job.error_message or "")

    async def test_discovery_triggered_on_later_attempts(self, db, make_update):
        """VulnForge discovery is called on attempt >= DISCOVERY_TRIGGER_AT_ATTEMPT."""
        from app.services.vulnforge_scan_worker import (
            DISCOVERY_TRIGGER_AT_ATTEMPT,
            process_pending_scan_jobs,
        )

        update = make_update(container_id=1, container_name="glances")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Set attempt count to the discovery threshold
        job = await _create_pending_job(
            db,
            update,
            trigger_attempt_count=DISCOVERY_TRIGGER_AT_ATTEMPT,
            last_trigger_attempt_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        # trigger_scan_by_name still fails, but discovery is called
        mock_client = _mock_vulnforge_client(trigger_scan_by_name=None)
        mock_client.trigger_container_discovery = AsyncMock(
            return_value={"total": 58, "discovered": ["glances"], "removed": 0}
        )

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        # Discovery should have been called
        mock_client.trigger_container_discovery.assert_called_once()
        # Job should still be pending (retrying), not failed
        assert job.status == "pending"
        assert job.trigger_attempt_count == DISCOVERY_TRIGGER_AT_ATTEMPT + 1

    async def test_discovery_not_called_on_early_attempts(self, db, make_update):
        """VulnForge discovery is NOT called on early attempts."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="glances")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # First attempt — discovery should not be triggered
        job = await _create_pending_job(db, update)

        mock_client = _mock_vulnforge_client(trigger_scan_by_name=None)
        mock_client.trigger_container_discovery = AsyncMock()

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        mock_client.trigger_container_discovery.assert_not_called()

    async def test_retry_succeeds_after_discovery(self, db, make_update):
        """Container found after discovery trigger — scan proceeds normally."""
        from app.services.vulnforge_scan_worker import (
            DISCOVERY_TRIGGER_AT_ATTEMPT,
            process_pending_scan_jobs,
        )

        update = make_update(container_id=1, container_name="glances")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        job = await _create_pending_job(
            db,
            update,
            trigger_attempt_count=DISCOVERY_TRIGGER_AT_ATTEMPT,
            last_trigger_attempt_at=datetime.now(UTC) - timedelta(minutes=5),
        )

        # This time trigger_scan_by_name succeeds (discovery found the container)
        mock_client = _mock_vulnforge_client()
        mock_client.trigger_container_discovery = AsyncMock(
            return_value={"total": 58, "discovered": ["glances"], "removed": 0}
        )

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        # Job should have transitioned to triggered
        assert job.status == "triggered"
        assert job.vulnforge_job_id == 42
        mock_client.trigger_container_discovery.assert_called_once()

    async def test_backoff_skips_cycle_when_too_early(self, db, make_update):
        """Worker skips retry when backoff timer hasn't elapsed."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="glances")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Attempt 3 just happened — needs 30s backoff
        job = await _create_pending_job(
            db,
            update,
            trigger_attempt_count=3,
            last_trigger_attempt_at=datetime.now(UTC),  # just now
        )

        mock_client = _mock_vulnforge_client(trigger_scan_by_name=None)

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            await process_pending_scan_jobs()
            await db.refresh(job)

        # Should be untouched — backoff not elapsed
        assert job.status == "pending"
        assert job.trigger_attempt_count == 3  # unchanged
        mock_client.trigger_scan_by_name.assert_not_called()

    async def test_full_retry_lifecycle(self, db, make_update):
        """End-to-end: fail twice, discover, succeed on third attempt."""
        from app.services.vulnforge_scan_worker import process_pending_scan_jobs

        update = make_update(container_id=1, container_name="glances")
        db.add(update)
        await db.commit()
        await db.refresh(update)

        # Create a matching UpdateHistory for CVE backfill
        history = UpdateHistory(
            container_id=1,
            update_id=update.id,
            container_name="glances",
            from_tag="4.4.0",
            to_tag="4.5.0.1",
            status="applied",
        )
        db.add(history)
        await db.commit()

        job = await _create_pending_job(db, update)

        # Build a client that fails twice then succeeds
        mock_client = _mock_vulnforge_client()
        call_count = 0

        async def _trigger_side_effect(_name: str):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return None  # container not found yet
            return {"job_ids": [42], "queued": 1}

        mock_client.trigger_scan_by_name = AsyncMock(side_effect=_trigger_side_effect)
        mock_client.trigger_container_discovery = AsyncMock(
            return_value={"total": 58, "discovered": ["glances"], "removed": 0}
        )

        session_patch, client_patch = await self._patch_session_and_client(db, mock_client)

        with session_patch, client_patch:
            # Cycle 1: attempt 0 → fail → attempt_count=1
            await process_pending_scan_jobs()
            await db.refresh(job)
            assert job.status == "pending"
            assert job.trigger_attempt_count == 1

            # Cycle 2: attempt 1 → fail → attempt_count=2
            # (no backoff needed for attempt 1)
            await process_pending_scan_jobs()
            await db.refresh(job)
            assert job.status == "pending"
            assert job.trigger_attempt_count == 2

            # Fast-forward backoff for attempt 2 (needs 30s)
            job.last_trigger_attempt_at = datetime.now(UTC) - timedelta(seconds=31)
            await db.commit()

            # Cycle 3: attempt 2 → discovery + trigger → succeeds!
            await process_pending_scan_jobs()
            await db.refresh(job)
            assert job.status == "triggered"
            assert job.vulnforge_job_id == 42
            mock_client.trigger_container_discovery.assert_called_once()

            # Cycle 4: polling → completed
            await process_pending_scan_jobs()
            await db.refresh(job)
            assert job.status == "completed"

        # Verify CVE data was written
        await db.refresh(update)
        assert update.cves_fixed == ["CVE-2024-0001", "CVE-2024-0002"]


# ---------------------------------------------------------------------------
# VulnForge client discovery tests
# ---------------------------------------------------------------------------


class TestVulnForgeClientDiscovery:
    """Tests for trigger_container_discovery()."""

    async def test_discovery_success(self):
        """Test successful discovery call."""
        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "total": 58,
            "discovered": ["glances"],
            "removed": 0,
            "message": "Discovered 1 new containers",
        }

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.post = AsyncMock(return_value=mock_response)

        result = await client.trigger_container_discovery()
        assert result is not None
        assert result["total"] == 58
        assert "glances" in result["discovered"]
        client.client.post.assert_called_once_with(
            "http://vulnforge:8787/api/v1/containers/discover"
        )

    async def test_discovery_connection_error(self):
        """Test discovery returns None on connection error."""
        import httpx

        from app.services.vulnforge_client import VulnForgeClient

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        result = await client.trigger_container_discovery()
        assert result is None

    async def test_discovery_server_error(self):
        """Test discovery returns None on HTTP error."""
        import httpx

        from app.services.vulnforge_client import VulnForgeClient

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Service Unavailable",
                request=MagicMock(),
                response=mock_response,
            )
        )

        client = VulnForgeClient(base_url="http://vulnforge:8787")
        client.client = AsyncMock()
        client.client.post = AsyncMock(return_value=mock_response)

        result = await client.trigger_container_discovery()
        assert result is None
