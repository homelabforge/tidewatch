"""Tests for the orphan-tag defense plan (2026-05-22).

Covers D9 continuity check, D10 lineage cap, D11 stale-tag heuristic,
D13 CVE delta gate, D14 major-change hold, and D16 DockerHub name filter
derivation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.registry_client import (
    DockerHubClient,
    LSCRClient,
    _is_continuous_major_jump,
)
from app.services.update_checker import UpdateChecker
from app.services.update_decision_maker import UpdateDecisionMaker

# ---------------------------------------------------------------------------
# Phase 1 (D9): continuity check on major jumps
# ---------------------------------------------------------------------------


class TestContinuityCheck:
    def test_plus_one_jump_passes(self):
        assert _is_continuous_major_jump(3, 4, {0, 1, 2, 3, 4}) is True

    def test_multi_major_missing_intermediates_rejected(self):
        # Lidarr incident: current=3, candidate=8, but no v4..v7.
        assert _is_continuous_major_jump(3, 8, {0, 1, 2, 3}) is False

    def test_multi_major_with_full_intermediates_passes(self):
        assert _is_continuous_major_jump(3, 8, {3, 4, 5, 6, 7, 8}) is True

    def test_same_major_passes(self):
        assert _is_continuous_major_jump(3, 3, {3}) is True

    def test_comparator_rejects_lidarr_orphan(self):
        client = LSCRClient()
        # current=3.1.0, candidate=8.1.2135, scope=major, no intermediates.
        accepted = client._compare_versions(
            "3.1.0",
            "8.1.2135",
            "major",
            available_majors={0, 1, 2, 3},
        )
        assert accepted is False

    def test_comparator_accepts_clean_plus_one(self):
        client = LSCRClient()
        accepted = client._compare_versions(
            "3.1.0",
            "4.0.0",
            "major",
            available_majors={0, 1, 2, 3, 4},
        )
        assert accepted is True


# ---------------------------------------------------------------------------
# Phase 8 (D16): DockerHub name= substring derivation
# ---------------------------------------------------------------------------


class TestNameSubstring:
    def test_patch_scope_emits_major_minor_dot(self):
        assert DockerHubClient._derive_name_substring("3.1.0", "patch") == "3.1."

    def test_minor_scope_emits_major_dot(self):
        assert DockerHubClient._derive_name_substring("3.1.0", "minor") == "3."

    def test_major_scope_omits_filter(self):
        assert DockerHubClient._derive_name_substring("3.1.0", "major") is None

    def test_v_prefix_stripped(self):
        assert DockerHubClient._derive_name_substring("v1.7.8", "patch") == "1.7."

    def test_non_semver_returns_none(self):
        assert DockerHubClient._derive_name_substring("latest", "patch") is None


# ---------------------------------------------------------------------------
# Phase 2 (D10) / Phase 3 (D11): decision-maker rejection paths
# ---------------------------------------------------------------------------


def _make_container(**overrides):
    container = MagicMock()
    container.current_tag = "3.1.0"
    container.scope = "patch"
    container.registry = "lscr"
    container.current_digest = None
    container.latest_lineage_cap_disabled = False
    container.last_digest_major = 3
    container.stable_anchor_tag = None
    container.accepted_anchor_major = None
    for k, v in overrides.items():
        setattr(container, k, v)
    return container


def _make_response(**kwargs):
    from app.services.tag_fetcher import FetchTagsResponse

    base = dict(
        latest_tag=None,
        latest_major_tag=None,
        all_tags=[],
        metadata=None,
        cache_hit=False,
        fetch_duration_ms=1.0,
    )
    base.update(kwargs)
    return FetchTagsResponse(**base)


class TestLatestLineageCap:
    def test_candidate_above_cap_rejected(self):
        decision_maker = UpdateDecisionMaker()
        container = _make_container()
        fetch = _make_response(
            latest_tag="8.1.2135",
            latest_lineage_major=3,
            latest_lineage_method="label",
        )
        decision = decision_maker.make_decision(container, fetch, include_prereleases=False)
        assert decision.has_update is False
        assert "latest_cap_skip" in decision.trace.trace

    def test_candidate_within_cap_passes(self):
        decision_maker = UpdateDecisionMaker()
        container = _make_container()
        fetch = _make_response(
            latest_tag="3.1.1",
            latest_lineage_major=3,
            latest_lineage_method="label",
        )
        decision = decision_maker.make_decision(container, fetch, include_prereleases=False)
        assert decision.has_update is True
        assert "latest_cap_skip" not in decision.trace.trace

    def test_opt_out_disables_cap(self):
        decision_maker = UpdateDecisionMaker()
        container = _make_container(latest_lineage_cap_disabled=True)
        fetch = _make_response(
            latest_tag="8.0.0",
            latest_lineage_major=3,
            latest_lineage_method="label",
        )
        decision = decision_maker.make_decision(container, fetch, include_prereleases=False)
        # The cap is disabled, so the candidate flows through (other checks
        # may still gate it but the trace must not record a cap skip).
        assert "latest_cap_skip" not in decision.trace.trace


class TestStaleTagHeuristic:
    def test_old_candidate_rejected(self):
        decision_maker = UpdateDecisionMaker()
        container = _make_container()
        now = datetime.now(UTC)
        fetch = _make_response(
            latest_tag="8.1.2135",
            latest_tag_pushed_at=now - timedelta(days=720),
            current_tag_pushed_at=now - timedelta(days=10),
        )
        decision = decision_maker.make_decision(container, fetch, include_prereleases=False)
        assert decision.has_update is False
        assert "stale_tag_skip" in decision.trace.trace

    def test_recent_candidate_passes(self):
        decision_maker = UpdateDecisionMaker()
        container = _make_container()
        now = datetime.now(UTC)
        fetch = _make_response(
            latest_tag="3.1.1",
            latest_tag_pushed_at=now,
            current_tag_pushed_at=now - timedelta(days=30),
        )
        decision = decision_maker.make_decision(container, fetch, include_prereleases=False)
        assert decision.has_update is True
        assert "stale_tag_skip" not in decision.trace.trace

    def test_within_slack_window_passes(self):
        decision_maker = UpdateDecisionMaker()
        container = _make_container()
        now = datetime.now(UTC)
        # Candidate pushed 2 days before current — well inside 7-day slack.
        fetch = _make_response(
            latest_tag="3.1.1",
            latest_tag_pushed_at=now - timedelta(days=2),
            current_tag_pushed_at=now,
        )
        decision = decision_maker.make_decision(container, fetch, include_prereleases=False)
        assert decision.has_update is True


# ---------------------------------------------------------------------------
# Phase 5 (D13): CVE delta gate
# ---------------------------------------------------------------------------


class TestCveDeltaGate:
    @pytest.mark.asyncio
    async def test_spike_blocks_auto_approval(self):
        container = MagicMock()
        container.policy = "auto"
        container.require_approval_for_major_change = False
        update = MagicMock()
        update.anomaly_held = False
        update.update_kind = "tag"
        update.vuln_delta = 576
        update.change_type = "patch"

        db = AsyncMock()
        from app.services.settings_service import SettingsService

        original = SettingsService.get_int

        async def fake_get_int(_db, key, default=0):
            if key == "cve_delta_block_threshold":
                return 50
            return await original(_db, key, default)

        SettingsService.get_int = fake_get_int  # type: ignore[assignment]
        try:
            approve, reason = await UpdateChecker._should_auto_approve(
                container, update, auto_update_enabled=True, db=db
            )
        finally:
            SettingsService.get_int = original  # type: ignore[assignment]

        assert approve is False
        assert "cve_delta_spike" in reason

    @pytest.mark.asyncio
    async def test_small_delta_passes(self):
        container = MagicMock()
        container.policy = "auto"
        container.require_approval_for_major_change = False
        update = MagicMock()
        update.anomaly_held = False
        update.update_kind = "tag"
        update.vuln_delta = 5
        update.change_type = "patch"

        db = AsyncMock()
        from app.services.settings_service import SettingsService

        original = SettingsService.get_int

        async def fake_get_int(_db, key, default=0):
            if key == "cve_delta_block_threshold":
                return 50
            return await original(_db, key, default)

        SettingsService.get_int = fake_get_int  # type: ignore[assignment]
        try:
            approve, _ = await UpdateChecker._should_auto_approve(
                container, update, auto_update_enabled=True, db=db
            )
        finally:
            SettingsService.get_int = original  # type: ignore[assignment]

        assert approve is True


# ---------------------------------------------------------------------------
# Phase 6 (D14): major-change-held gate
# ---------------------------------------------------------------------------


class TestMajorChangeHold:
    @pytest.mark.asyncio
    async def test_major_change_held_blocks(self):
        container = MagicMock()
        container.policy = "auto"
        container.require_approval_for_major_change = True
        update = MagicMock()
        update.anomaly_held = False
        update.update_kind = "tag"
        update.vuln_delta = 0
        update.change_type = "major"

        approve, reason = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )
        assert approve is False
        assert "major_change_held" in reason

    @pytest.mark.asyncio
    async def test_minor_change_passes(self):
        container = MagicMock()
        container.policy = "auto"
        container.require_approval_for_major_change = True
        update = MagicMock()
        update.anomaly_held = False
        update.update_kind = "tag"
        update.vuln_delta = 0
        update.change_type = "minor"

        approve, _ = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )
        assert approve is True

    @pytest.mark.asyncio
    async def test_explicit_optout_allows_major(self):
        container = MagicMock()
        container.policy = "auto"
        container.require_approval_for_major_change = False
        update = MagicMock()
        update.anomaly_held = False
        update.update_kind = "tag"
        update.vuln_delta = 0
        update.change_type = "major"

        approve, _ = await UpdateChecker._should_auto_approve(
            container, update, auto_update_enabled=True
        )
        assert approve is True
