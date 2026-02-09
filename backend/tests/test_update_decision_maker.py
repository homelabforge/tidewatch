"""Tests for update decision maker (app/services/update_decision_maker.py).

Tests the pure-logic decision layer that determines if updates are available:
- No update scenarios
- Tag-based update detection
- Digest-based update detection (non-semver tags)
- Digest baseline storage on first run (Fix 2)
- Scope violation detection
- Fetch error handling
- Non-semver tag expansion (lts, stable, alpine, edge)
"""

import pytest

from app.models.container import Container
from app.services.tag_fetcher import FetchTagsResponse
from app.services.update_decision_maker import UpdateDecisionMaker


def make_container(**overrides) -> Container:
    """Create a Container with sensible defaults."""
    defaults = {
        "id": 1,
        "name": "test-app",
        "image": "nginx",
        "current_tag": "1.0.0",
        "current_digest": None,
        "registry": "docker.io",
        "compose_file": "/compose/test.yml",
        "service_name": "test",
        "policy": "monitor",
        "scope": "patch",
        "vulnforge_enabled": False,
        "include_prereleases": None,
    }
    defaults.update(overrides)
    return Container(**defaults)


def make_fetch_response(**overrides) -> FetchTagsResponse:
    """Create a FetchTagsResponse with sensible defaults."""
    defaults = {
        "latest_tag": None,
        "latest_major_tag": None,
        "all_tags": ["1.0.0"],
        "metadata": None,
        "cache_hit": False,
        "fetch_duration_ms": 50.0,
        "error": None,
    }
    defaults.update(overrides)
    return FetchTagsResponse(**defaults)


class TestNoUpdate:
    """Test scenarios where no update is available."""

    def test_no_update_same_version(self):
        """No update when latest_tag matches current_tag."""
        container = make_container(current_tag="1.0.0")
        response = make_fetch_response(latest_tag=None)

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is False
        assert decision.update_kind is None
        assert decision.latest_tag is None

    def test_no_update_empty_tags(self):
        """No update when registry returns no tags."""
        container = make_container()
        response = make_fetch_response(latest_tag=None, all_tags=[])

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is False

    def test_no_update_latest_tag_matches_current(self):
        """No update when latest_tag equals current_tag."""
        container = make_container(current_tag="1.2.3")
        response = make_fetch_response(latest_tag="1.2.3")

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is False


class TestTagUpdate:
    """Test tag-based update detection."""

    def test_patch_update_detected(self):
        """Detect patch version update."""
        container = make_container(current_tag="1.0.0", scope="patch")
        response = make_fetch_response(latest_tag="1.0.1")

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.update_kind == "tag"
        assert decision.latest_tag == "1.0.1"
        assert decision.change_type == "patch"

    def test_minor_update_detected(self):
        """Detect minor version update."""
        container = make_container(current_tag="1.0.0", scope="minor")
        response = make_fetch_response(latest_tag="1.1.0")

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.update_kind == "tag"
        assert decision.latest_tag == "1.1.0"

    def test_major_update_detected(self):
        """Detect major version update."""
        container = make_container(current_tag="1.0.0", scope="major")
        response = make_fetch_response(latest_tag="2.0.0")

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.update_kind == "tag"
        assert decision.latest_tag == "2.0.0"


class TestDigestUpdate:
    """Test digest-based update detection for non-semver tags."""

    def test_digest_change_detected(self):
        """Detect digest change on 'latest' tag."""
        container = make_container(
            current_tag="latest",
            current_digest="sha256:old_digest",
        )
        response = make_fetch_response(
            metadata={"digest": "sha256:new_digest"},
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.update_kind == "digest"
        assert decision.digest_changed is True
        assert decision.new_digest == "sha256:new_digest"

    def test_digest_unchanged(self):
        """No update when digest is the same."""
        container = make_container(
            current_tag="latest",
            current_digest="sha256:same_digest",
        )
        response = make_fetch_response(
            metadata={"digest": "sha256:same_digest"},
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is False
        assert decision.digest_changed is False

    def test_digest_baseline_first_run(self):
        """First run: digest_baseline_needed set when current_digest is None (Fix 2)."""
        container = make_container(
            current_tag="latest",
            current_digest=None,  # First run — no baseline
        )
        response = make_fetch_response(
            metadata={"digest": "sha256:initial_digest"},
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is False  # Not an "update", just baseline
        assert decision.digest_baseline_needed is True
        assert decision.new_digest == "sha256:initial_digest"
        assert decision.digest_changed is False

    def test_non_semver_lts_tag_digest_tracking(self):
        """Digest tracking works for 'lts' tag (Fix 9)."""
        container = make_container(
            current_tag="lts",
            current_digest="sha256:old_lts",
        )
        response = make_fetch_response(
            metadata={"digest": "sha256:new_lts"},
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.update_kind == "digest"

    def test_non_semver_stable_tag_digest_tracking(self):
        """Digest tracking works for 'stable' tag (Fix 9)."""
        container = make_container(
            current_tag="stable",
            current_digest="sha256:old_stable",
        )
        response = make_fetch_response(
            metadata={"digest": "sha256:new_stable"},
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.update_kind == "digest"

    def test_semver_tag_ignores_metadata(self):
        """Semver tags should not trigger digest-based updates."""
        container = make_container(
            current_tag="1.2.3",
            current_digest="sha256:old",
        )
        response = make_fetch_response(
            metadata={"digest": "sha256:new"},
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        # Even though metadata has a different digest, semver tags use tag comparison
        assert decision.has_update is False
        assert decision.digest_changed is False


class TestScopeViolation:
    """Test scope violation detection."""

    def test_scope_violation_major_blocked(self):
        """Detect scope violation when major update exists but scope is patch."""
        container = make_container(current_tag="1.0.0", scope="patch")
        response = make_fetch_response(
            latest_tag=None,  # No in-scope update
            latest_major_tag="2.0.0",
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is False
        assert decision.is_scope_violation is True
        assert decision.latest_major_tag == "2.0.0"

    def test_no_scope_violation_when_in_scope_update_exists(self):
        """No scope violation when in-scope and major update are the same."""
        container = make_container(current_tag="1.0.0", scope="minor")
        response = make_fetch_response(
            latest_tag="1.1.0",
            latest_major_tag="1.1.0",  # Same as in-scope
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.is_scope_violation is False

    def test_scope_violation_with_in_scope_update(self):
        """Both in-scope update and scope violation detected simultaneously."""
        container = make_container(current_tag="1.0.0", scope="patch")
        response = make_fetch_response(
            latest_tag="1.0.1",  # In-scope patch update
            latest_major_tag="2.0.0",  # Out-of-scope major
        )

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is True
        assert decision.is_scope_violation is True
        assert decision.latest_tag == "1.0.1"
        assert decision.latest_major_tag == "2.0.0"


class TestFetchError:
    """Test error handling for fetch failures."""

    def test_fetch_error_returns_no_update(self):
        """Fetch error should return no-update decision."""
        container = make_container()
        response = make_fetch_response(error="Connection timeout")

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is False
        assert decision.update_kind is None
        assert decision.is_scope_violation is False

    def test_fetch_error_preserves_trace(self):
        """Fetch error should record anomaly in trace."""
        container = make_container()
        response = make_fetch_response(error="Rate limited: 429")

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        trace_json = decision.trace.to_json()
        assert "429" in trace_json


class TestVersionComparison:
    """Regression tests for version comparison (Fix 4)."""

    @pytest.mark.parametrize(
        "current,latest,expected_update",
        [
            ("1.9.9", "1.10.0", True),  # Lexicographic would fail this
            ("2.0.0-rc1", "2.0.0", True),  # Pre-release to stable
            ("v1.2.3", "v1.2.4", True),  # With v prefix
            ("1.0.0", "1.0.0", False),  # Same version
        ],
    )
    def test_version_comparison_correctness(self, current, latest, expected_update):
        """Version comparison uses semantic ordering, not lexicographic."""
        container = make_container(current_tag=current, scope="minor")
        response = make_fetch_response(latest_tag=latest if expected_update else None)

        decision = UpdateDecisionMaker().make_decision(container, response, False)

        assert decision.has_update is expected_update
