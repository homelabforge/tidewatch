"""Tests for sibling drift detection + safety-net reconciliation.

Covers the narrow reconciler in
:mod:`app.services.sibling_reconciliation`. The reconciler's job is:

- Detect sibling groups where containers share ``(compose_file, registry, image)``.
- Record drift entries when siblings have differing ``current_tag`` or
  differing effective check settings.
- Auto-create missing Update records only for siblings whose group has
  identical settings AND identical ``current_tag`` as the dominant tag, using
  a shared fetch response (main-pass safety net).
- Never create speculative Update records for drifted-tag siblings (resolution
  goes via the runbook).
"""

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.container import Container
from app.services.sibling_reconciliation import (
    SiblingDrift,
    _effective_prereleases,
    _settings_signature,
    reconcile_siblings,
)


@dataclass
class FakeDecision:
    """Minimal stand-in for UpdateDecision."""

    has_update: bool = True
    latest_tag: str = "2026.2.2"


@dataclass
class FakeFetchResponse:
    """Minimal stand-in for FetchTagsResponse."""

    latest_tag: str | None = "2026.2.2"
    latest_major_tag: str | None = None
    all_tags: list[str] = field(default_factory=list)
    metadata: dict | None = None
    cache_hit: bool = True
    fetch_duration_ms: float = 0.0
    calver_blocked_tag: str | None = None
    error: str | None = None


def _make_container(
    id: int,
    name: str,
    image: str = "goauthentik/server",
    current_tag: str = "2026.2.1",
    scope: str = "major",
    include_prereleases: bool | None = None,
    version_track: str | None = None,
    policy: str = "auto",
    compose_file: str = "/compose/network.yml",
    registry: str = "ghcr",
) -> Container:
    """Build a Container model instance with the fields the reconciler reads."""
    return Container(
        id=id,
        name=name,
        image=image,
        current_tag=current_tag,
        registry=registry,
        compose_file=compose_file,
        service_name=name,
        policy=policy,
        scope=scope,
        include_prereleases=include_prereleases,
        version_track=version_track,
        vulnforge_enabled=False,
        update_available=False,
    )


@pytest.fixture
def mock_db():
    import contextlib

    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    @contextlib.asynccontextmanager
    async def fake_begin_nested():
        yield

    db.begin_nested = fake_begin_nested
    return db


@pytest.fixture
def mock_run_context():
    return MagicMock()


@pytest.fixture
def mock_rate_limiter():
    return MagicMock()


class TestHelpers:
    def test_effective_prereleases_explicit_true(self):
        container = _make_container(1, "c", include_prereleases=True)
        assert _effective_prereleases(container, global_default=False) is True

    def test_effective_prereleases_explicit_false(self):
        container = _make_container(1, "c", include_prereleases=False)
        assert _effective_prereleases(container, global_default=True) is False

    def test_effective_prereleases_inherits_global_when_none(self):
        container = _make_container(1, "c", include_prereleases=None)
        assert _effective_prereleases(container, global_default=True) is True

    def test_settings_signature_matches_identical_settings(self):
        a = _make_container(1, "a", scope="patch", version_track="calver")
        b = _make_container(2, "b", scope="patch", version_track="calver")
        assert _settings_signature(a, False) == _settings_signature(b, False)

    def test_settings_signature_distinguishes_version_track(self):
        a = _make_container(1, "a", scope="major", version_track=None)
        b = _make_container(2, "b", scope="major", version_track="calver")
        assert _settings_signature(a, False) != _settings_signature(b, False)


class TestReconcileSiblings:
    """Tests for the post-main-pass reconciler."""

    @pytest.mark.asyncio
    async def test_disabled_setting_short_circuits(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """When sibling_reconciliation_enabled=false, nothing runs."""
        containers = [
            _make_container(1, "authentik-server"),
            _make_container(2, "authentik-worker"),
        ]
        with patch(
            "app.services.sibling_reconciliation.SettingsService.get_bool",
            new=AsyncMock(return_value=False),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                containers,
                updated_ids=set(),
                global_prereleases=False,
            )
        assert drifts == []

    @pytest.mark.asyncio
    async def test_single_sibling_group_is_ignored(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """A container with no sibling is never reconciled or reported."""
        containers = [
            _make_container(1, "standalone", image="nginx", compose_file="/compose/a.yml"),
            _make_container(2, "other", image="redis", compose_file="/compose/b.yml"),
        ]
        with patch(
            "app.services.sibling_reconciliation.SettingsService.get_bool",
            new=AsyncMock(return_value=True),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                containers,
                updated_ids=set(),
                global_prereleases=False,
            )
        assert drifts == []

    @pytest.mark.asyncio
    async def test_disabled_policy_excluded_from_groups(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """Disabled containers do not participate in sibling detection."""
        containers = [
            _make_container(1, "authentik-server", current_tag="2026.2.2"),
            _make_container(2, "authentik-worker", current_tag="2026.2.1", policy="disabled"),
        ]
        with patch(
            "app.services.sibling_reconciliation.SettingsService.get_bool",
            new=AsyncMock(return_value=True),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                containers,
                updated_ids=set(),
                global_prereleases=False,
            )
        assert drifts == []

    @pytest.mark.asyncio
    async def test_safety_net_creates_missing_update_for_identical_sibling(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """The one auto-create path: identical settings, identical current_tag,
        one sibling already updated in the main pass, the other should get an
        Update via reconciliation using the shared fetch response.
        """
        server = _make_container(1, "authentik-server", current_tag="2026.2.1")
        worker = _make_container(2, "authentik-worker", current_tag="2026.2.1")

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_tags_for_container = AsyncMock(return_value=FakeFetchResponse())
        mock_decision_maker = MagicMock()
        mock_decision_maker.make_decision = MagicMock(return_value=FakeDecision(has_update=True))

        apply_decision_mock = AsyncMock(return_value=MagicMock())

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateDecisionMaker",
                return_value=mock_decision_maker,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=apply_decision_mock,
            ),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids={1},  # server already handled by main pass
                global_prereleases=False,
            )

        # No drift detected (same tag, same settings)
        assert drifts == []
        # apply_decision called exactly once for the worker
        assert apply_decision_mock.await_count == 1
        assert apply_decision_mock.await_args is not None
        called_container = apply_decision_mock.await_args.args[1]
        assert called_container.id == 2

    @pytest.mark.asyncio
    async def test_skips_siblings_already_updated_by_main_pass(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """Siblings already in updated_ids must not get duplicate Update records."""
        server = _make_container(1, "authentik-server", current_tag="2026.2.1")
        worker = _make_container(2, "authentik-worker", current_tag="2026.2.1")

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_tags_for_container = AsyncMock(return_value=FakeFetchResponse())
        mock_decision_maker = MagicMock()
        mock_decision_maker.make_decision = MagicMock(return_value=FakeDecision(has_update=True))

        apply_decision_mock = AsyncMock()

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateDecisionMaker",
                return_value=mock_decision_maker,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=apply_decision_mock,
            ),
        ):
            await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids={1, 2},  # both already handled
                global_prereleases=False,
            )

        apply_decision_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_drifted_tag_reports_drift_but_no_auto_create(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """Two siblings, same settings, DIFFERENT current_tag → drift reported,
        but reconciliation must NOT speculatively create an Update for the
        lagging sibling. This is the exact bug that started the incident.
        """
        server = _make_container(1, "authentik-server", current_tag="2026.2.2")
        worker = _make_container(2, "authentik-worker", current_tag="2026.2.1")

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_tags_for_container = AsyncMock(return_value=FakeFetchResponse())
        mock_decision_maker = MagicMock()
        mock_decision_maker.make_decision = MagicMock(return_value=FakeDecision(has_update=True))

        apply_decision_mock = AsyncMock()

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateDecisionMaker",
                return_value=mock_decision_maker,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=apply_decision_mock,
            ),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids={1},
                global_prereleases=False,
            )

        # Exactly one drift entry describing both siblings
        assert len(drifts) == 1
        drift = drifts[0]
        assert isinstance(drift, SiblingDrift)
        assert set(drift.sibling_names) == {"authentik-server", "authentik-worker"}
        assert drift.per_container_tags == {
            "authentik-server": "2026.2.2",
            "authentik-worker": "2026.2.1",
        }
        assert drift.settings_divergent is False
        assert drift.has_tag_drift is True
        # Worker is NOT auto-created — apply_decision never called for worker
        # (server is in updated_ids, worker is drifted-tag → skip)
        assert apply_decision_mock.await_count == 0
        assert drift.reconciled_names == []

    @pytest.mark.asyncio
    async def test_divergent_settings_reports_drift_no_auto_create(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """Two siblings with different version_track → drift reported but
        reconciliation must NOT use the shared FetchTagsResponse (that's the
        bug Codex flagged).
        """
        server = _make_container(1, "authentik-server", current_tag="2026.2.1", version_track=None)
        worker = _make_container(
            2, "authentik-worker", current_tag="2026.2.1", version_track="calver"
        )

        apply_decision_mock = AsyncMock()
        # Also assert TagFetcher is never constructed for the divergent-settings case
        mock_fetcher_cls = MagicMock()

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                mock_fetcher_cls,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=apply_decision_mock,
            ),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids=set(),
                global_prereleases=False,
            )

        assert len(drifts) == 1
        assert drifts[0].settings_divergent is True
        assert drifts[0].has_tag_drift is False
        apply_decision_mock.assert_not_called()
        mock_fetcher_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_error_skips_reconciliation(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """A fetch error on the representative should skip auto-creation for
        that group without raising or producing a drift entry (no drift to
        report when tags and settings all match)."""
        server = _make_container(1, "authentik-server", current_tag="2026.2.1")
        worker = _make_container(2, "authentik-worker", current_tag="2026.2.1")

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_tags_for_container = AsyncMock(
            return_value=FakeFetchResponse(error="rate limited")
        )
        apply_decision_mock = AsyncMock()

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=apply_decision_mock,
            ),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids={1},
                global_prereleases=False,
            )

        assert drifts == []
        apply_decision_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_update_decision_skips_auto_create(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """When the decision says no update is available, the loop never calls
        apply_decision — verifies the has_update short-circuit."""
        server = _make_container(1, "authentik-server", current_tag="2026.2.2")
        worker = _make_container(2, "authentik-worker", current_tag="2026.2.2")

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_tags_for_container = AsyncMock(return_value=FakeFetchResponse())
        mock_decision_maker = MagicMock()
        mock_decision_maker.make_decision = MagicMock(return_value=FakeDecision(has_update=False))

        apply_decision_mock = AsyncMock()

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateDecisionMaker",
                return_value=mock_decision_maker,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=apply_decision_mock,
            ),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids={1},
                global_prereleases=False,
            )

        assert drifts == []
        apply_decision_mock.assert_not_called()


class TestDriftPersistence:
    """Tests for SiblingDriftEvent persistence via savepoint isolation."""

    @pytest.mark.asyncio
    async def test_drift_persists_sibling_drift_event(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """When drift is detected, a SiblingDriftEvent row is persisted."""
        from app.models.sibling_drift_event import SiblingDriftEvent

        server = _make_container(1, "authentik-server", current_tag="2026.2.2")
        worker = _make_container(2, "authentik-worker", current_tag="2026.2.1")

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_tags_for_container = AsyncMock(return_value=FakeFetchResponse())
        mock_decision_maker = MagicMock()
        mock_decision_maker.make_decision = MagicMock(return_value=FakeDecision(has_update=True))

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateDecisionMaker",
                return_value=mock_decision_maker,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=AsyncMock(),
            ),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids={1},
                global_prereleases=False,
                job_id=42,
            )

        assert len(drifts) == 1
        # Verify db.add was called with a SiblingDriftEvent
        assert mock_db.add.call_count == 1
        event = mock_db.add.call_args.args[0]
        assert isinstance(event, SiblingDriftEvent)
        assert event.image == "goauthentik/server"
        assert event.job_id == 42
        assert event.settings_divergent is False
        assert event.reconciliation_attempted is True

    @pytest.mark.asyncio
    async def test_drift_reconciliation_attempted_false_for_divergent_settings(
        self, mock_db, mock_run_context, mock_rate_limiter
    ):
        """When settings diverge, reconciliation_attempted should be False."""
        from app.models.sibling_drift_event import SiblingDriftEvent

        server = _make_container(1, "authentik-server", current_tag="2026.2.1", version_track=None)
        worker = _make_container(
            2, "authentik-worker", current_tag="2026.2.1", version_track="calver"
        )

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                MagicMock(),
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=AsyncMock(),
            ),
        ):
            drifts = await reconcile_siblings(
                mock_db,
                mock_run_context,
                mock_rate_limiter,
                [server, worker],
                updated_ids=set(),
                global_prereleases=False,
                job_id=99,
            )

        assert len(drifts) == 1
        assert drifts[0].settings_divergent is True
        event = mock_db.add.call_args.args[0]
        assert isinstance(event, SiblingDriftEvent)
        assert event.reconciliation_attempted is False
        assert event.job_id == 99

    @pytest.mark.asyncio
    async def test_drift_persistence_failure_does_not_abort_subsequent_groups(
        self, mock_run_context, mock_rate_limiter
    ):
        """A failed drift insert for one group should not prevent processing
        of subsequent groups (savepoint isolation).
        """
        import contextlib

        db = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.add = MagicMock()

        call_count = 0

        @contextlib.asynccontextmanager
        async def failing_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated savepoint failure")
            yield

        db.begin_nested = failing_then_ok
        db.flush = AsyncMock()

        # Two groups with drift: different compose files
        group_a = [
            _make_container(1, "app-server", current_tag="1.0.0", compose_file="/a.yml"),
            _make_container(2, "app-worker", current_tag="1.0.1", compose_file="/a.yml"),
        ]
        group_b = [
            _make_container(3, "db-primary", current_tag="2.0.0", compose_file="/b.yml"),
            _make_container(4, "db-replica", current_tag="2.0.1", compose_file="/b.yml"),
        ]

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_tags_for_container = AsyncMock(return_value=FakeFetchResponse())
        mock_decision_maker = MagicMock()
        mock_decision_maker.make_decision = MagicMock(return_value=FakeDecision(has_update=False))

        with (
            patch(
                "app.services.sibling_reconciliation.SettingsService.get_bool",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.sibling_reconciliation.TagFetcher",
                return_value=mock_fetcher,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateDecisionMaker",
                return_value=mock_decision_maker,
            ),
            patch(
                "app.services.sibling_reconciliation.UpdateChecker.apply_decision",
                new=AsyncMock(),
            ),
        ):
            drifts = await reconcile_siblings(
                db,
                mock_run_context,
                mock_rate_limiter,
                group_a + group_b,
                updated_ids=set(),
                global_prereleases=False,
                job_id=77,
            )

        # Both groups should still produce drift entries
        assert len(drifts) == 2
        # The second group's persistence should have succeeded
        assert db.add.call_count >= 1
