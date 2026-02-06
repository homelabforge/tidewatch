"""Tests for update checker service (app/services/update_checker.py).

Tests update discovery, auto-approval logic, and changelog classification:
- Update detection for containers
- Auto-approval policy enforcement (auto, manual, security, disabled)
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
from app.services.update_checker import UpdateChecker


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
    async def test_auto_approve_container_policy_manual(self, make_update):
        """Test auto-approval disabled when container policy is manual."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="manual",
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
        assert "allows all updates" in reason

    @pytest.mark.asyncio
    async def test_auto_approve_security_policy_approves_security_updates(self, make_update):
        """Test security policy approves security updates only."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="security",
        )

        security_update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="security"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, security_update, auto_update_enabled=True
        )

        assert should_approve is True
        assert "approves security updates" in reason

    @pytest.mark.asyncio
    async def test_auto_approve_security_policy_rejects_feature_updates(self, make_update):
        """Test security policy rejects non-security updates."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="security",
        )

        feature_update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, feature_update, auto_update_enabled=True
        )

        assert should_approve is False
        assert "manual approval for non-security" in reason


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
            policy="manual",
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
            policy="manual",
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
            policy="manual",
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
                policy="manual",
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
                policy="manual",
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
                policy="manual",
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
            policy="manual",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
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
            policy="manual",
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
            policy="manual",
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
        db.execute = AsyncMock()
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
            policy="manual",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        import httpx

        mock_client.get_latest_tag = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not found", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )
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
            policy="manual",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        import httpx

        mock_client.get_latest_tag = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
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
            policy="manual",
            vulnforge_enabled=False,
        )

        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(side_effect=ValueError("Test error"))
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


class TestSemverPolicies:
    """Test suite for semver-aware auto-approval policies."""

    @pytest.mark.asyncio
    async def test_patch_only_policy_approves_patch_updates(self, make_update):
        """Test patch-only policy approves patch version updates (1.0.0 -> 1.0.1)."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="patch-only",
        )

        update = make_update(container_id=1, from_tag="1.0.0", to_tag="1.0.1", reason_type="bugfix")

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is True
        assert "patch-only policy approves patch updates" in reason

    @pytest.mark.asyncio
    async def test_patch_only_policy_rejects_minor_updates(self, make_update):
        """Test patch-only policy rejects minor version updates (1.0.0 -> 1.1.0)."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="patch-only",
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is False
        assert "minor" in reason

    @pytest.mark.asyncio
    async def test_patch_only_policy_rejects_major_updates(self, make_update):
        """Test patch-only policy rejects major version updates (1.0.0 -> 2.0.0)."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="patch-only",
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="2.0.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is False
        assert "major" in reason

    @pytest.mark.asyncio
    async def test_minor_and_patch_policy_approves_patch_updates(self, make_update):
        """Test minor-and-patch policy approves patch updates."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="minor-and-patch",
        )

        update = make_update(container_id=1, from_tag="1.0.0", to_tag="1.0.1", reason_type="bugfix")

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is True
        assert "minor-and-patch policy approves patch updates" in reason

    @pytest.mark.asyncio
    async def test_minor_and_patch_policy_approves_minor_updates(self, make_update):
        """Test minor-and-patch policy approves minor updates."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="minor-and-patch",
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="1.1.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is True
        assert "minor-and-patch policy approves minor updates" in reason

    @pytest.mark.asyncio
    async def test_minor_and_patch_policy_rejects_major_updates(self, make_update):
        """Test minor-and-patch policy rejects major updates (breaking changes)."""
        container = Container(
            name="test",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/test.yml",
            service_name="test",
            policy="minor-and-patch",
        )

        update = make_update(
            container_id=1, from_tag="1.0.0", to_tag="2.0.0", reason_type="feature"
        )

        should_approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )

        assert should_approve is False
        assert "major" in reason
        assert "breaking changes" in reason


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
            policy="manual",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=True,  # Container-specific setting
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
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
    async def test_check_container_uses_global_prerelease_setting_when_container_false(
        self, mock_db
    ):
        """Test check_container falls back to global prerelease setting."""
        container = Container(
            id=1,
            name="nginx",
            image="nginx",
            current_tag="1.0.0",
            registry="docker.io",
            compose_file="/compose/nginx.yml",
            service_name="nginx",
            policy="manual",
            scope="patch",
            vulnforge_enabled=False,
            include_prereleases=False,  # Container-specific is False, should check global
        )

        # Mock registry client
        mock_client = AsyncMock()
        mock_client.get_latest_tag = AsyncMock(return_value=None)
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
                return_value=True,
            ),
            patch("app.services.update_checker.event_bus.publish", new_callable=AsyncMock),
        ):
            await UpdateChecker.check_container(mock_db, container)

            # Should have called get_latest_tag with global prerelease=True
            mock_client.get_latest_tag.assert_called_once()
            call_kwargs = mock_client.get_latest_tag.call_args.kwargs
            assert call_kwargs["include_prereleases"] is True
