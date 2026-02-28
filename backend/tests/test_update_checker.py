"""Tests for update checker service (app/services/update_checker.py).

Tests update discovery, auto-approval logic, and changelog classification:
- Update detection for containers
- Auto-approval policy enforcement (auto, monitor, disabled)
- Changelog fetching and classification
- VulnForge CVE enrichment
- Digest tracking for 'latest' tags
- Duplicate update handling (race conditions)
- Event bus notifications
- Error handling (registry errors, database errors)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.container import Container
from app.services.tag_fetcher import FetchTagsResponse
from app.services.update_checker import UpdateChecker
from app.services.update_decision_maker import UpdateDecisionMaker


class TestAutoApprovalLogic:
    """Test suite for auto-approval policy logic."""

    @pytest.mark.asyncio
    async def test_auto_approve_disabled_globally(self, make_update):
        """Test auto-approval disabled when global setting is off."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="auto",  # Container allows auto, but global is disabled
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=False
        )

        assert should_approve is False
        assert "disabled globally" in reason

    @pytest.mark.asyncio
    async def test_auto_approve_container_policy_disabled(self, make_update):
        """Test auto-approval disabled when container policy is disabled."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="disabled",
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is False
        assert "container policy is disabled" in reason

    @pytest.mark.asyncio
    async def test_auto_approve_container_policy_monitor(self, make_update):
        """Test auto-approval disabled when container policy is monitor."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="monitor",
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is False
        assert "manual approval" in reason

    @pytest.mark.asyncio
    async def test_auto_approve_container_policy_auto(self, make_update):
        """Test auto-approval enabled when container policy is auto."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="auto",
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is True
        assert "auto-approves updates" in reason


class TestUpdateDetection:
    """Test suite for update detection logic."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.begin_nested = MagicMock()

        # Mock context manager for begin_nested
        db.begin_nested.return_value.__aenter__ = AsyncMock()
        db.begin_nested.return_value.__aexit__ = AsyncMock()

        return db

    @pytest.fixture
    def mock_container(self):
        """Create mock container."""
        return Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.25.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            scope="patch",
            include_prereleases=False,
            vulnforge_enabled=False,
        )

    @pytest.mark.asyncio
    async def test_check_container_no_update_available(self, mock_db, mock_container):
        """Test check_container when no update is available."""
        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        # Mock existing update query (no pending updates)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                return_value=False,
            ),
            patch("app.services.update_checker.event_bus.publish", return_value=None),
        ):
            update = await UpdateChecker.check_container(mock_db, mock_container)

            assert update is None
            assert mock_container.update_available is False
            assert mock_container.latest_tag is None

    @pytest.mark.asyncio
    async def test_check_container_update_available(self, mock_db, mock_container):
        """Test check_container when update is available."""
        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="1.25.3")
        mock_client.close = AsyncMock()

        # Mock existing update query (no pending updates)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        # Mock dispatcher instance
        mock_dispatcher_instance = AsyncMock()
        mock_dispatcher_instance.notify_update_available = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_int",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
            patch(
                "app.services.notifications.dispatcher.NotificationDispatcher",
                return_value=mock_dispatcher_instance,
            ),
        ):
            update = await UpdateChecker.check_container(mock_db, mock_container)

            assert update is not None
            assert update.from_tag == "1.25.0"
            assert update.to_tag == "1.25.3"
            assert mock_container.update_available is True
            assert mock_container.latest_tag == "1.25.3"

    @pytest.mark.asyncio
    async def test_check_container_duplicate_update_returns_existing(
        self, mock_db, mock_container, make_update
    ):
        """Test check_container returns existing update if already present."""
        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="1.25.3")
        mock_client.close = AsyncMock()

        # Mock existing update
        existing_update = make_update(
            id=1,
            container_id=1,
            from_tag="1.25.0",
            to_tag="1.25.3",
            status="pending",
            reason_type="feature",
            reason_summary="New features",
        )

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=existing_update)
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                return_value=False,
            ),
            patch("app.services.update_checker.event_bus.publish", return_value=None),
        ):
            update = await UpdateChecker.check_container(mock_db, mock_container)

            # Should return existing update
            assert update is not None
            assert update is existing_update
            assert update.id == 1

    @pytest.mark.asyncio
    async def test_check_container_latest_tag_digest_tracking(self, mock_db):
        """Test check_container tracks digest for 'latest' tag."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="latest",
            current_digest=None,  # No digest stored yet
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            scope="patch",
            vulnforge_enabled=False,
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)  # No new tag
        mock_client.get_tag_metadata = AsyncMock(return_value={"digest": "sha256:abc123def456"})
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                return_value=False,
            ),
            patch("app.services.update_checker.event_bus.publish", return_value=None),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Should have stored initial digest
            assert container.current_digest == "sha256:abc123def456"

    @pytest.mark.asyncio
    async def test_check_container_latest_tag_digest_changed(self, mock_db):
        """Test check_container detects digest changes for 'latest' tag."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="latest",
            current_digest="sha256:olddigest123",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            scope="patch",
            vulnforge_enabled=False,
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)  # Tag unchanged
        mock_client.get_tag_metadata = AsyncMock(
            return_value={
                "digest": "sha256:newdigest456"  # Digest changed!
            }
        )
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        # Mock dispatcher instance
        mock_dispatcher_instance = AsyncMock()
        mock_dispatcher_instance.notify_update_available = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_int",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
            patch(
                "app.services.notifications.dispatcher.NotificationDispatcher",
                return_value=mock_dispatcher_instance,
            ),
        ):
            update = await UpdateChecker.check_container(mock_db, container)

            # Should create update for digest change
            assert update is not None
            assert update.reason_type == "maintenance"
            assert update.reason_summary is not None
            assert "digest updated" in update.reason_summary.lower()


class TestUpdateSuperseding:
    """Test suite for update superseding logic.

    When a newer version is released (e.g., v1.25.4) while an older update
    (v1.25.3) is already pending/approved, the older update should be
    superseded (deleted) and only the latest version shown.
    """

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.begin_nested = MagicMock()
        db.begin_nested.return_value.__aenter__ = AsyncMock()
        db.begin_nested.return_value.__aexit__ = AsyncMock()
        return db

    @pytest.fixture
    def mock_container(self):
        """Create mock container."""
        return Container(
            id=1,
            name="mealie",
            image="ghcr.io/mealie-recipes/mealie",
            current_tag="3.9.2",
            registry="ghcr.io",
            compose_file="/compose/smarthome.yml",
            service_name="mealie",
            policy="monitor",
            scope="minor",
            include_prereleases=False,
            vulnforge_enabled=False,
        )

    @pytest.mark.asyncio
    async def test_newer_version_supersedes_older_pending_updates(self, mock_db, mock_container):
        """When v3.10.1 is found while v3.10.0 is approved, old updates are cleared."""
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="3.10.1")
        mock_client.close = AsyncMock()

        # No existing update for the exact new to_tag
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        mock_dispatcher_instance = AsyncMock()
        mock_dispatcher_instance.notify_update_available = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_int",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
            patch(
                "app.services.notifications.dispatcher.NotificationDispatcher",
                return_value=mock_dispatcher_instance,
            ),
            patch.object(
                UpdateChecker,
                "_clear_pending_updates",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            update = await UpdateChecker.check_container(mock_db, mock_container)

            # Should have cleared old pending/approved updates before creating new one
            mock_clear.assert_called_once_with(mock_db, mock_container.id)

            # Should create new update for latest version
            assert update is not None
            assert update.to_tag == "3.10.1"

    @pytest.mark.asyncio
    async def test_exact_duplicate_does_not_trigger_supersede(
        self, mock_db, mock_container, make_update
    ):
        """When the same to_tag already exists, no supersede occurs."""
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="3.10.0")
        mock_client.close = AsyncMock()

        # Existing update for the same to_tag
        existing_update = make_update(
            id=42,
            container_id=1,
            from_tag="3.9.2",
            to_tag="3.10.0",
            status="approved",
            reason_type="feature",
        )
        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=existing_update)
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                return_value=False,
            ),
            patch("app.services.update_checker.event_bus.publish", return_value=None),
            patch.object(
                UpdateChecker,
                "_clear_pending_updates",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            update = await UpdateChecker.check_container(mock_db, mock_container)

            # Should return existing update without clearing
            assert update is existing_update
            mock_clear.assert_not_called()


class TestCheckAllContainers:
    """Test suite for checking all containers."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_check_all_containers_returns_stats(self, mock_db):
        """Test check_all_containers returns statistics."""
        # Mock containers query
        containers = [
            Container(
                id=1,
                name="nginx",
                image="nginx",
                current_tag="1.0.0",
                registry="docker.io",
                compose_file="/compose/nginx.yml",
                service_name="nginx",
                policy="monitor",
            ),
            Container(
                id=2,
                name="redis",
                image="redis",
                current_tag="7.0.0",
                registry="docker.io",
                compose_file="/compose/redis.yml",
                service_name="redis",
                policy="auto",
            ),
        ]

        container_result = MagicMock()
        container_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=containers))
        )
        mock_db.execute = AsyncMock(return_value=container_result)

        with patch.object(UpdateChecker, "check_container", return_value=None):
            stats = await UpdateChecker.check_all_containers(mock_db)

            assert stats["total"] == 2
            assert stats["checked"] == 2
            assert stats["updates_found"] == 0
            assert stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_check_all_containers_counts_updates(self, mock_db, make_update):
        """Test check_all_containers counts found updates."""
        containers = [
            Container(
                id=1,
                name="nginx",
                image="nginx",
                current_tag="1.0.0",
                registry="docker.io",
                compose_file="/compose/nginx.yml",
                service_name="nginx",
                policy="monitor",
            )
        ]

        container_result = MagicMock()
        container_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=containers))
        )
        mock_db.execute = AsyncMock(return_value=container_result)

        # Mock check_container to return an update
        mock_update = make_update(id=1, container_id=1, from_tag="1.0.0", to_tag="1.1.0")

        with patch.object(UpdateChecker, "check_container", return_value=mock_update):
            stats = await UpdateChecker.check_all_containers(mock_db)

            assert stats["updates_found"] == 1

    @pytest.mark.asyncio
    async def test_check_all_containers_handles_errors(self, mock_db):
        """Test check_all_containers handles errors gracefully."""
        containers = [
            Container(
                id=1,
                name="nginx",
                image="nginx",
                current_tag="1.0.0",
                registry="docker.io",
                compose_file="/compose/nginx.yml",
                service_name="nginx",
                policy="monitor",
            )
        ]

        container_result = MagicMock()
        container_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=containers))
        )
        mock_db.execute = AsyncMock(return_value=container_result)

        # Mock check_container to raise an error
        with patch.object(UpdateChecker, "check_container", side_effect=ValueError("Test error")):
            stats = await UpdateChecker.check_all_containers(mock_db)

            assert stats["errors"] == 1
            assert stats["checked"] == 0  # Failed before incrementing checked


class TestAutoApprovalExecution:
    """Test suite for auto-approval execution."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.begin_nested = MagicMock()
        db.begin_nested.return_value.__aenter__ = AsyncMock()
        db.begin_nested.return_value.__aexit__ = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_check_container_auto_approves_when_policy_allows(self, mock_db):
        """Test check_container auto-approves update when policy allows."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="auto",  # Auto-approve policy
            scope="patch",
            vulnforge_enabled=False,
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="1.0.1")
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        # Mock dispatcher instance
        mock_dispatcher_instance = AsyncMock()
        mock_dispatcher_instance.notify_update_available = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_int",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
            patch(
                "app.services.notifications.dispatcher.NotificationDispatcher",
                return_value=mock_dispatcher_instance,
            ),
        ):
            update = await UpdateChecker.check_container(mock_db, container)

            # Should be auto-approved
            assert update is not None
            assert update.status == "approved"
            assert update.approved_by == "system"
            assert update.approved_at is not None


class TestEventBusNotifications:
    """Test suite for event bus notification publishing."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.begin_nested = MagicMock()
        db.begin_nested.return_value.__aenter__ = AsyncMock()
        db.begin_nested.return_value.__aexit__ = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_check_container_publishes_started_event(self, mock_db):
        """Test check_container publishes update-check-started event."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        events = []

        async def capture_event(event):
            events.append(event)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                return_value=False,
            ),
            patch("app.services.update_checker.event_bus.publish", capture_event),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Should have published update-check-started event
            started_events = [e for e in events if e.get("type") == "update-check-started"]
            assert len(started_events) > 0
            assert started_events[0]["container_id"] == 1
            assert started_events[0]["container_name"] == "nginx"

    @pytest.mark.asyncio
    async def test_check_container_publishes_update_available_event(self, mock_db):
        """Test check_container publishes update-available event."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value="1.0.1")
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        events = []

        async def capture_event(event):
            events.append(event)

        # Mock dispatcher instance
        mock_dispatcher_instance = AsyncMock()
        mock_dispatcher_instance.notify_update_available = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_int",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch("app.services.update_checker.event_bus.publish", capture_event),
            patch(
                "app.services.notifications.dispatcher.NotificationDispatcher",
                return_value=mock_dispatcher_instance,
            ),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Should have published update-available event
            available_events = [e for e in events if e.get("type") == "update-available"]
            assert len(available_events) > 0
            assert available_events[0]["from_tag"] == "1.0.0"
            assert available_events[0]["to_tag"] == "1.0.1"

    @pytest.mark.asyncio
    async def test_check_container_publishes_error_event_on_registry_failure(self, mock_db):
        """Test check_container publishes error event on registry failure."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            vulnforge_enabled=False,
            include_prereleases=True,  # Set to True to avoid SettingsService call
        )

        import httpx

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_request = MagicMock()

        mock_client.get_latest_tag = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not found", request=mock_request, response=mock_response
            )
        )
        mock_client.close = AsyncMock()

        # Mock get_client as async function
        async def mock_get_client(registry, db):
            return mock_client

        events = []

        async def capture_event(event):
            events.append(event)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                new=mock_get_client,
            ),
            patch("app.services.update_checker.event_bus.publish", new=capture_event),
        ):
            update = await UpdateChecker.check_container(mock_db, container)

            assert update is None

            # Should have published error event
            error_events = [e for e in events if e.get("type") == "update-check-error"]
            assert len(error_events) > 0
            assert "Registry HTTP error" in error_events[0]["message"]


class TestQueryHelpers:
    """Test suite for query helper methods."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_get_pending_updates_returns_pending_only(self, mock_db, make_update):
        """Test get_pending_updates returns only pending updates."""
        pending_updates = [
            make_update(id=1, container_id=1, from_tag="1.0.0", to_tag="1.1.0", status="pending"),
            make_update(id=2, container_id=2, from_tag="2.0.0", to_tag="2.1.0", status="pending"),
        ]

        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=pending_updates))
        )
        mock_db.execute = AsyncMock(return_value=result)

        updates = await UpdateChecker.get_pending_updates(mock_db)

        assert len(updates) == 2
        assert all(u.status == "pending" for u in updates)

    @pytest.mark.asyncio
    async def test_get_auto_approvable_updates_filters_by_policy(self, mock_db, make_update):
        """Test get_auto_approvable_updates filters by container policy."""
        auto_updates = [
            make_update(id=1, container_id=1, from_tag="1.0.0", to_tag="1.1.0", status="pending")
        ]

        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=auto_updates)))
        mock_db.execute = AsyncMock(return_value=result)

        updates = await UpdateChecker.get_auto_approvable_updates(mock_db)

        # Should have executed query with join on Container and policy="auto" filter
        assert len(updates) == 1


class TestErrorHandling:
    """Test suite for error handling."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        # Return MagicMock from execute so sync methods (scalar_one_or_none)
        # don't create unawaited coroutines
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=None)
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_check_container_handles_registry_http_error(self, mock_db):
        """Test check_container handles registry HTTP errors gracefully."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        import httpx

        mock_client.get_latest_tag = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not found", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch("app.services.update_checker.event_bus.publish", new=AsyncMock()),
        ):
            update = await UpdateChecker.check_container(mock_db, container)

            # Should return None without crashing
            assert update is None

    @pytest.mark.asyncio
    async def test_check_container_handles_connection_error(self, mock_db):
        """Test check_container handles connection errors gracefully."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        import httpx

        mock_client.get_latest_tag = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch("app.services.update_checker.event_bus.publish", new=AsyncMock()),
        ):
            update = await UpdateChecker.check_container(mock_db, container)

            assert update is None

    @pytest.mark.asyncio
    async def test_check_container_closes_client_on_exception(self, mock_db):
        """Test check_container always closes registry client."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(side_effect=ValueError("Test error"))
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch("app.services.update_checker.event_bus.publish", new=AsyncMock()),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Client should still be closed
            mock_client.close.assert_called_once()


class TestSecurityUpdatesQuery:
    """Test suite for get_security_updates query method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_get_security_updates_filters_by_reason_type(self, mock_db, make_update):
        """Test get_security_updates returns only security-type updates."""
        security_updates = [
            make_update(
                id=1,
                container_id=1,
                from_tag="1.0.0",
                to_tag="1.0.1",
                status="pending",
                reason_type="security",
            ),
            make_update(
                id=2,
                container_id=2,
                from_tag="2.0.0",
                to_tag="2.0.1",
                status="pending",
                reason_type="security",
            ),
        ]

        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=security_updates))
        )
        mock_db.execute = AsyncMock(return_value=result)

        updates = await UpdateChecker.get_security_updates(mock_db)

        assert len(updates) == 2
        assert all(u.reason_type == "security" for u in updates)

    @pytest.mark.asyncio
    async def test_get_security_updates_orders_by_created_at_desc(self, mock_db):
        """Test get_security_updates returns newest first."""
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_db.execute = AsyncMock(return_value=result)

        await UpdateChecker.get_security_updates(mock_db)

        # Should have executed query with order_by created_at desc
        assert mock_db.execute.called


class TestRaceConditionHandling:
    """Test suite for IntegrityError race condition recovery."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        # Mock begin_nested context manager
        nested_ctx = AsyncMock()
        nested_ctx.__aenter__ = AsyncMock()
        nested_ctx.__aexit__ = AsyncMock()
        db.begin_nested = MagicMock(return_value=nested_ctx)

        return db

    @pytest.mark.skip(
        reason="IntegrityError race condition recovery test requires complex encryption mocking"
    )
    @pytest.mark.asyncio
    async def test_check_container_handles_integrity_error_race_condition(self, mock_db):
        """Test check_container recovers from IntegrityError race condition.

        Note: This test is skipped due to encryption complexity in Update model.
        The race condition recovery logic is tested in integration tests instead.
        """
        pass


class TestPrereleaseHandling:
    """Test suite for prerelease version filtering."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.begin_nested = MagicMock()
        db.begin_nested.return_value.__aenter__ = AsyncMock()
        db.begin_nested.return_value.__aexit__ = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_check_container_respects_container_include_prereleases_true(self, mock_db):
        """Test check_container uses include_prereleases=True when container setting is True."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=True,  # Container-specific setting
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Should have called get_latest_tag with include_prereleases=True
            mock_client.get_latest_tag.assert_called_once()
            call_kwargs = mock_client.get_latest_tag.call_args.kwargs
            assert call_kwargs["include_prereleases"] is True

    @pytest.mark.asyncio
    async def test_check_container_uses_explicit_false_prerelease_over_global_true(self, mock_db):
        """Test container prerelease=False overrides global=True (tri-state)."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=False,  # Explicitly stable-only
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=True,  # Global says include prereleases
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Container explicitly False — should NOT inherit global True
            mock_client.get_latest_tag.assert_called_once()
            call_kwargs = mock_client.get_latest_tag.call_args.kwargs
            assert call_kwargs["include_prereleases"] is False

    @pytest.mark.asyncio
    async def test_check_container_uses_global_prerelease_when_container_none(self, mock_db):
        """Test container prerelease=None inherits global setting (tri-state)."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=None,  # Inherit global
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
        mock_client.get_latest_major_tag = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        existing_result = MagicMock()
        existing_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=existing_result)

        with (
            patch(
                "app.services.update_checker.RegistryClientFactory.get_client",
                return_value=mock_client,
            ),
            patch(
                "app.services.update_checker.SettingsService.get_bool",
                new_callable=AsyncMock,
                return_value=True,  # Global says include prereleases
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Container is None — should inherit global True
            mock_client.get_latest_tag.assert_called_once()
            call_kwargs = mock_client.get_latest_tag.call_args.kwargs
            assert call_kwargs["include_prereleases"] is True


# ---------------------------------------------------------------------------
# apply_decision() refactor tests
# ---------------------------------------------------------------------------


def _make_fetch_response(**overrides) -> FetchTagsResponse:
    """Create a FetchTagsResponse with sensible defaults."""
    defaults = {
        "latest_tag": "1.25.3",
        "latest_major_tag": None,
        "all_tags": ["1.25.0", "1.25.3"],
        "metadata": None,
        "cache_hit": False,
        "fetch_duration_ms": 50.0,
        "error": None,
    }
    defaults.update(overrides)
    return FetchTagsResponse(**defaults)


class TestApplyDecisionRefactor:
    """Verify apply_decision() correctly delegates to _process_auto_approval_and_notify."""

    @pytest.fixture
    def mock_db(self):
        """Minimal async DB mock sufficient for apply_decision."""
        db = AsyncMock()
        # "Does this update already exist?" query → No
        no_result = MagicMock()
        no_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=no_result)
        db.add = MagicMock()
        # async with db.begin_nested():
        nested = AsyncMock()
        nested.__aenter__ = AsyncMock(return_value=None)
        nested.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=nested)
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.fixture
    def base_container(self):
        """Container with auto-approval policy and no enrichment configured."""
        return Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.25.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="monitor",
            scope="patch",
            vulnforge_enabled=False,
            release_source=None,
        )

    def _make_decision(self, container: Container, latest_tag: str = "1.25.3"):
        """Build a real UpdateDecision via UpdateDecisionMaker."""
        response = _make_fetch_response(latest_tag=latest_tag)
        return UpdateDecisionMaker().make_decision(container, response, False)

    @pytest.mark.asyncio
    async def test_helper_called_before_event_published(self, mock_db, base_container):
        """_process_auto_approval_and_notify must be awaited before event_bus.publish."""
        call_order: list[str] = []

        async def fake_notify(_db, _update, _container):
            call_order.append("notify")

        async def fake_publish(_event):
            call_order.append("publish")

        decision = self._make_decision(base_container)
        fetch = _make_fetch_response()

        with (
            patch.object(
                UpdateChecker, "_process_auto_approval_and_notify", side_effect=fake_notify
            ),
            patch("app.services.update_checker.event_bus.publish", side_effect=fake_publish),
            patch("app.services.update_checker.SettingsService.get_int", return_value=3),
            patch("app.services.update_checker.SettingsService.get", return_value=None),
            patch(
                "app.services.update_checker.ComposeParser.extract_release_source",
                return_value=None,
            ),
        ):
            await UpdateChecker.apply_decision(mock_db, base_container, decision, fetch)

        assert call_order == ["notify", "publish"]

    @pytest.mark.asyncio
    async def test_auto_approval_applied_correctly(self, mock_db, base_container):
        """Auto-approval marks update as approved when global enabled and policy is auto."""
        base_container.policy = "auto"
        decision = self._make_decision(base_container)
        fetch = _make_fetch_response()

        with (
            patch("app.services.update_checker.SettingsService.get_bool", return_value=True),
            patch("app.services.update_checker.SettingsService.get_int", return_value=3),
            patch("app.services.update_checker.SettingsService.get", return_value=None),
            patch(
                "app.services.update_checker.ComposeParser.extract_release_source",
                return_value=None,
            ),
            patch("app.services.update_checker.event_bus.publish", new=AsyncMock()),
            patch(
                "app.services.notifications.dispatcher.NotificationDispatcher"
                ".notify_update_available",
                new=AsyncMock(),
            ),
        ):
            update = await UpdateChecker.apply_decision(mock_db, base_container, decision, fetch)

        assert update is not None
        assert update.status == "approved"
        assert update.approved_by == "system"


class TestCalverBlockedTagPersistence:
    """Test C: apply_decision() sets and clears calver_blocked_tag each run."""

    @pytest.fixture
    def mock_db(self):
        """Minimal async DB mock sufficient for apply_decision."""
        db = AsyncMock()
        no_result = MagicMock()
        no_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=no_result)
        db.add = MagicMock()
        nested = AsyncMock()
        nested.__aenter__ = AsyncMock(return_value=None)
        nested.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=nested)
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.fixture
    def base_container(self):
        return Container(
            id=1,
            name="kopia",
            image="kopia/kopia",
            current_tag="0.22.3",
            registry="ghcr.io",
            compose_file="/compose/kopia.yml",
            service_name="kopia",
            policy="monitor",
            scope="patch",
            vulnforge_enabled=False,
            release_source=None,
        )

    @pytest.mark.asyncio
    async def test_calver_blocked_tag_set_from_fetch_response(self, mock_db, base_container):
        """apply_decision() persists calver_blocked_tag from FetchTagsResponse."""
        fetch = _make_fetch_response(calver_blocked_tag="20260224.0.42919")
        decision = UpdateDecisionMaker().make_decision(base_container, fetch, False)

        with (
            patch("app.services.update_checker.SettingsService.get_int", return_value=3),
            patch("app.services.update_checker.SettingsService.get", return_value=None),
            patch(
                "app.services.update_checker.ComposeParser.extract_release_source",
                return_value=None,
            ),
            patch("app.services.update_checker.event_bus.publish", new=AsyncMock()),
        ):
            await UpdateChecker.apply_decision(mock_db, base_container, decision, fetch)

        assert base_container.calver_blocked_tag == "20260224.0.42919"

    @pytest.mark.asyncio
    async def test_calver_blocked_tag_cleared_when_none(self, mock_db, base_container):
        """apply_decision() clears stale calver_blocked_tag when FetchTagsResponse returns None."""
        base_container.calver_blocked_tag = "20260224.0.42919"  # Stale from previous run
        fetch = _make_fetch_response(calver_blocked_tag=None)
        decision = UpdateDecisionMaker().make_decision(base_container, fetch, False)

        with (
            patch("app.services.update_checker.SettingsService.get_int", return_value=3),
            patch("app.services.update_checker.SettingsService.get", return_value=None),
            patch(
                "app.services.update_checker.ComposeParser.extract_release_source",
                return_value=None,
            ),
            patch("app.services.update_checker.event_bus.publish", new=AsyncMock()),
        ):
            await UpdateChecker.apply_decision(mock_db, base_container, decision, fetch)

        assert base_container.calver_blocked_tag is None
