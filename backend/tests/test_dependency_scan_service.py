"""Tests for DependencyScanService job orchestration."""

from app.services.dependency_scan_service import DependencyScanService


class TestGetOrCreateJob:
    """get_or_create_job atomically dedups concurrent scan requests (R1-H3).

    A manual "Scan Dep" request and the scheduled scan must not both observe
    "no active job" and start overlapping runs.
    """

    async def test_dedups_active_job(self, db, make_container):
        """A second caller receives the existing active job, not a new one."""
        container = make_container(name="depscan-proj", is_my_project=True)
        db.add(container)
        await db.commit()

        job1, created1 = await DependencyScanService.get_or_create_job(db, triggered_by="user")
        job2, created2 = await DependencyScanService.get_or_create_job(db, triggered_by="scheduler")

        assert created1 is True
        assert created2 is False
        assert job1.id == job2.id

    async def test_creates_when_idle(self, db):
        """With no active job, a new queued job is created."""
        job, created = await DependencyScanService.get_or_create_job(db, triggered_by="scheduler")

        assert created is True
        assert job.status == "queued"
        assert job.triggered_by == "scheduler"
