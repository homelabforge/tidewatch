"""Regression tests for metrics_collector.

The collector previously held a DB session across slow per-container docker
calls (~91s for 43 containers), blocking every other API request that needed
a session. The session-not-held tests below assert the new three-phase design.

It also has a batched fast-path (one ``docker ps`` + one ``docker stats c1 c2 …``)
and a per-container concurrent fallback path. Tests cover both.
"""

import asyncio
from unittest.mock import patch

import pytest

from app.services.metrics_collector import metrics_collector

# Reusable stub stats payload (matches DockerStatsService.get_*_stats output)
_STATS = {
    "cpu_percent": 1.0,
    "memory_usage": 100,
    "memory_limit": 200,
    "memory_percent": 50.0,
    "network_rx": 0,
    "network_tx": 0,
    "block_read": 0,
    "block_write": 0,
    "pids": 1,
}


@pytest.fixture
def session_lifecycle_tracker(db):
    """Patch AsyncSessionLocal where metrics_collector uses it.

    Tracks how many sessions are entered/exited so tests can assert the
    collector closes its read-phase session BEFORE issuing docker calls.
    Returns the same backing `db` (in-memory test DB) on each enter, but
    properly tracks the lifecycle.
    """
    events: list[str] = []

    class TrackedSession:
        def __init__(self):
            self._open = False

        def __call__(self):
            return self

        async def __aenter__(self):
            events.append("enter")
            self._open = True
            return db

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            events.append("exit")
            self._open = False
            return False

    tracker = TrackedSession()
    with patch("app.services.metrics_collector.AsyncSessionLocal", tracker):
        yield events, tracker


# ─── batched fast-path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batched_path_releases_session_across_docker_awaits(
    db, session_lifecycle_tracker, make_container
):
    """Batched path: collector must NOT hold a DB session during docker calls.

    Pre-fix the collector held one transaction for the entire ~91s loop on
    StaticPool's single connection, blocking all other DB queries. New design
    closes the read session before docker calls begin.
    """
    events, tracker = session_lifecycle_tracker

    db.add(make_container(name="alpha"))
    db.add(make_container(name="beta"))
    await db.commit()

    docker_calls_with_open_session: list[str] = []

    async def fake_list_running():
        if tracker._open:
            docker_calls_with_open_session.append("list_running")
        return {"alpha", "beta"}

    async def fake_batched_stats(names):
        if tracker._open:
            docker_calls_with_open_session.append(f"batched_stats:{','.join(names)}")
        return {n: dict(_STATS) for n in names}

    with (
        patch(
            "app.services.metrics_collector.docker_stats_service.list_running_container_names",
            new=fake_list_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.get_batched_stats",
            new=fake_batched_stats,
        ),
    ):
        result = await metrics_collector.collect_all_metrics()

    assert result["collected"] == 2
    assert result["skipped"] == 0
    assert result["errors"] == 0
    assert docker_calls_with_open_session == [], (
        f"Docker calls happened while a DB session was open: "
        f"{docker_calls_with_open_session} — pool starvation regression"
    )
    # Two distinct sessions: phase 1 (read) and phase 3 (write)
    assert events == ["enter", "exit", "enter", "exit"], (
        f"Expected exactly two open/close pairs, got {events}"
    )


@pytest.mark.asyncio
async def test_batched_path_skips_non_running_containers(
    db, session_lifecycle_tracker, make_container
):
    """Containers not in the docker ps result are marked skipped, not errored."""
    db.add(make_container(name="running1"))
    db.add(make_container(name="running2"))
    db.add(make_container(name="stopped"))
    await db.commit()

    async def fake_list_running():
        return {"running1", "running2"}  # 'stopped' is missing

    requested_names: list[list[str]] = []

    async def fake_batched_stats(names):
        requested_names.append(names)
        return {n: dict(_STATS) for n in names}

    with (
        patch(
            "app.services.metrics_collector.docker_stats_service.list_running_container_names",
            new=fake_list_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.get_batched_stats",
            new=fake_batched_stats,
        ),
    ):
        result = await metrics_collector.collect_all_metrics()

    assert result["collected"] == 2
    assert result["skipped"] == 1
    assert result["errors"] == 0
    # Only the running containers were sent to batched stats
    assert len(requested_names) == 1
    assert set(requested_names[0]) == {"running1", "running2"}


@pytest.mark.asyncio
async def test_batched_path_handles_batch_failure(db, session_lifecycle_tracker, make_container):
    """If get_batched_stats returns empty (batch aborted), all running marked error."""
    db.add(make_container(name="alpha"))
    db.add(make_container(name="beta"))
    await db.commit()

    async def fake_list_running():
        return {"alpha", "beta"}

    async def fake_batched_stats(_names):
        return {}  # Simulate "Error response from daemon: No such container..."

    with (
        patch(
            "app.services.metrics_collector.docker_stats_service.list_running_container_names",
            new=fake_list_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.get_batched_stats",
            new=fake_batched_stats,
        ),
    ):
        result = await metrics_collector.collect_all_metrics()

    assert result["collected"] == 0
    assert result["errors"] == 2
    assert result["skipped"] == 0


@pytest.mark.asyncio
async def test_batched_path_handles_partial_stats_response(
    db, session_lifecycle_tracker, make_container
):
    """Containers missing from the batched stats result are marked errored individually."""
    db.add(make_container(name="alpha"))
    db.add(make_container(name="beta"))
    db.add(make_container(name="charlie"))
    await db.commit()

    async def fake_list_running():
        return {"alpha", "beta", "charlie"}

    async def fake_batched_stats(_names):
        # Stats only returned for two of three (e.g. third was unparseable)
        return {"alpha": dict(_STATS), "charlie": dict(_STATS)}

    with (
        patch(
            "app.services.metrics_collector.docker_stats_service.list_running_container_names",
            new=fake_list_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.get_batched_stats",
            new=fake_batched_stats,
        ),
    ):
        result = await metrics_collector.collect_all_metrics()

    assert result["collected"] == 2
    assert result["errors"] == 1
    assert result["skipped"] == 0


# ─── fallback per-container path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fallback_path_used_when_docker_ps_fails(
    db, session_lifecycle_tracker, make_container
):
    """When list_running_container_names returns None, fall back to per-container."""
    db.add(make_container(name="alpha"))
    db.add(make_container(name="beta"))
    await db.commit()

    fallback_calls: list[str] = []

    async def fake_list_running():
        return None  # Force fallback

    async def fake_running(name):
        fallback_calls.append(f"check_running:{name}")
        return True

    async def fake_stats(name):
        fallback_calls.append(f"get_stats:{name}")
        return dict(_STATS)

    with (
        patch(
            "app.services.metrics_collector.docker_stats_service.list_running_container_names",
            new=fake_list_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.check_container_running",
            new=fake_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.get_container_stats",
            new=fake_stats,
        ),
    ):
        result = await metrics_collector.collect_all_metrics()

    assert result["collected"] == 2
    assert result["errors"] == 0
    assert any("check_running:alpha" in c for c in fallback_calls)
    assert any("get_stats:beta" in c for c in fallback_calls)


@pytest.mark.asyncio
async def test_fallback_one_bad_container_does_not_abort_cycle(
    db, session_lifecycle_tracker, make_container
):
    """One docker timeout/exception in the fallback path must not propagate."""
    db.add(make_container(name="good"))
    db.add(make_container(name="bad"))
    await db.commit()

    async def fake_list_running():
        return None  # Force fallback

    async def fake_running(name):
        if name == "bad":
            # Bare TimeoutError — what asyncio.wait_for raises in
            # check_container_running. Pre-fix this would propagate.
            raise TimeoutError("docker inspect timed out")
        return True

    async def fake_stats(_name):
        return dict(_STATS)

    with (
        patch(
            "app.services.metrics_collector.docker_stats_service.list_running_container_names",
            new=fake_list_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.check_container_running",
            new=fake_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.get_container_stats",
            new=fake_stats,
        ),
    ):
        result = await metrics_collector.collect_all_metrics()

    assert result["collected"] == 1, "Good container should still be collected"
    assert result["errors"] == 1, "Bad container should be counted as error"


@pytest.mark.asyncio
async def test_fallback_concurrency_setting_clamped(db, session_lifecycle_tracker, make_container):
    """metrics_concurrency setting must be clamped to [1, 16] in the fallback path."""
    from app.services.settings_service import SettingsService

    db.add(make_container(name="c1"))
    await db.commit()
    await SettingsService.set(db, "metrics_concurrency", "999")  # out-of-range

    captured_sem_value: list[int] = []
    real_semaphore = asyncio.Semaphore

    def tracking_semaphore(value: int):
        captured_sem_value.append(value)
        return real_semaphore(value)

    async def fake_list_running():
        return None  # Force fallback (where the semaphore is used)

    async def fake_running(_name):
        return False  # skip; we only want to capture the semaphore size

    with (
        patch("asyncio.Semaphore", new=tracking_semaphore),
        patch(
            "app.services.metrics_collector.docker_stats_service.list_running_container_names",
            new=fake_list_running,
        ),
        patch(
            "app.services.metrics_collector.docker_stats_service.check_container_running",
            new=fake_running,
        ),
    ):
        await metrics_collector.collect_all_metrics()

    assert captured_sem_value, "Semaphore was not constructed (fallback never ran)"
    assert captured_sem_value[0] == 16, f"Expected clamp to 16, got {captured_sem_value[0]}"


@pytest.mark.asyncio
async def test_collect_all_metrics_empty_container_list(db, session_lifecycle_tracker):
    """No containers → no errors, no docker calls, returns zeros."""
    result = await metrics_collector.collect_all_metrics()
    assert result == {"collected": 0, "skipped": 0, "errors": 0}
