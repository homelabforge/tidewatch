"""Tests for app.services.channel_anchor pure-logic helpers.

Network-driven resolution is exercised by registry-client tests.
This module locks down the pure logic: label extraction, manifest-list
platform picking, label-blob walking, the AnchorCache TTL, and the
fresh-vs-accepted state machine (Phase 5.4 / codex finding R1-H2).
"""

from __future__ import annotations

import pytest

from app.services.channel_anchor import (
    AnchorCache,
    AnchorDecision,
    AnchorResolution,
    decide_anchor_bound,
    extract_anchor_major,
    labels_from_config_blob,
    pick_platform_manifest,
)


class TestExtractAnchorMajor:
    """`extract_anchor_major` parses label values into a major version int."""

    def test_oci_image_version_clean(self):
        assert extract_anchor_major("org.opencontainers.image.version", "4.0.17") == 4

    def test_oci_image_version_with_v_prefix(self):
        assert extract_anchor_major("org.opencontainers.image.version", "v4.0.17") == 4

    def test_oci_image_version_with_build_tail(self):
        # LinuxServer-style "4.0.17.2952-ls311" in an OCI label value.
        assert extract_anchor_major("org.opencontainers.image.version", "4.0.17.2952-ls311") == 4

    def test_linuxserver_build_version_full_sentence(self):
        """R1-H1: LinuxServer's free-form sentence must yield major=4."""
        value = "LinuxServer.io version: 4.0.17.2952-ls311 Build-date: 2026-05-12T00:00:00+00:00"
        assert extract_anchor_major("build_version", value) == 4

    def test_linuxserver_build_version_with_v_prefix(self):
        value = "LinuxServer.io version: v4.0.17-ls311 Build-date: 2026-05-12T00:00:00+00:00"
        assert extract_anchor_major("build_version", value) == 4

    def test_returns_none_for_empty_value(self):
        assert extract_anchor_major("build_version", "") is None
        assert extract_anchor_major("org.opencontainers.image.version", "   ") is None

    def test_returns_none_for_unparseable_value(self):
        assert extract_anchor_major("build_version", "no version here") is None
        assert extract_anchor_major("org.opencontainers.image.version", "latest") is None

    def test_v5_beta_label_returns_5(self):
        """Sanity check for the channel-shift detection path."""
        value = "LinuxServer.io version: 5.0.0.6928-develop-ls300 Build-date: ..."
        assert extract_anchor_major("build_version", value) == 5


class TestPickPlatformManifest:
    """`pick_platform_manifest` selects the host-arch child from an index."""

    @pytest.fixture
    def index_amd64_arm64(self):
        return [
            {
                "digest": "sha256:amd64deadbeef",
                "platform": {"os": "linux", "architecture": "amd64"},
            },
            {
                "digest": "sha256:arm64deadbeef",
                "platform": {"os": "linux", "architecture": "arm64"},
            },
        ]

    def test_picks_preferred_arch(self, index_amd64_arm64):
        amd64 = pick_platform_manifest(index_amd64_arm64, preferred_arch="amd64")
        assert amd64 is not None and amd64["digest"] == "sha256:amd64deadbeef"

        arm64 = pick_platform_manifest(index_amd64_arm64, preferred_arch="arm64")
        assert arm64 is not None and arm64["digest"] == "sha256:arm64deadbeef"

    def test_falls_back_to_amd64_when_preferred_missing(self):
        index = [
            {
                "digest": "sha256:amd64deadbeef",
                "platform": {"os": "linux", "architecture": "amd64"},
            },
        ]
        # Asked for arm64 but only amd64 published — fall back, don't crash.
        result = pick_platform_manifest(index, preferred_arch="arm64")
        assert result is not None and result["digest"] == "sha256:amd64deadbeef"

    def test_filters_non_linux(self):
        index = [
            {"digest": "windows", "platform": {"os": "windows", "architecture": "amd64"}},
            {"digest": "linux-amd64", "platform": {"os": "linux", "architecture": "amd64"}},
        ]
        result = pick_platform_manifest(index, preferred_arch="amd64")
        assert result is not None and result["digest"] == "linux-amd64"

    def test_empty_index_returns_none(self):
        assert pick_platform_manifest([]) is None


class TestLabelsFromConfigBlob:
    """Walks .config.Labels (or .container_config.Labels fallback)."""

    def test_oci_labels(self):
        blob = {
            "config": {
                "Labels": {
                    "org.opencontainers.image.version": "4.0.17",
                    "build_version": "LinuxServer.io version: 4.0.17.2952-ls311 ...",
                }
            }
        }
        labels = labels_from_config_blob(blob)
        assert labels["org.opencontainers.image.version"] == "4.0.17"
        assert "build_version" in labels

    def test_legacy_container_config_fallback(self):
        blob = {
            "container_config": {"Labels": {"org.label-schema.version": "3.2.1"}},
        }
        assert labels_from_config_blob(blob) == {"org.label-schema.version": "3.2.1"}

    def test_returns_empty_dict_when_no_labels(self):
        assert labels_from_config_blob({}) == {}
        assert labels_from_config_blob({"config": {}}) == {}
        assert labels_from_config_blob({"config": {"Labels": None}}) == {}


class TestAnchorCache:
    """TTL behavior of the dedicated anchor cache (Phase 5.5 / R1-F4)."""

    def test_get_returns_none_for_missing_key(self):
        cache = AnchorCache()
        assert cache.get("dockerhub", "linuxserver/sonarr", "latest") is None

    def test_set_then_get(self):
        cache = AnchorCache()
        resolution = AnchorResolution(
            anchor_major=4,
            digest="sha256:abc",
            source_label="build_version",
            raw_label_value="LinuxServer.io version: 4.0.17.2952-ls311 ...",
        )
        cache.set("dockerhub", "linuxserver/sonarr", "latest", resolution)
        assert cache.get("dockerhub", "linuxserver/sonarr", "latest") == resolution

    def test_invalidate(self):
        cache = AnchorCache()
        resolution = AnchorResolution(4, "sha256:abc", "build_version", "")
        cache.set("dockerhub", "linuxserver/sonarr", "latest", resolution)
        cache.invalidate("dockerhub", "linuxserver/sonarr", "latest")
        assert cache.get("dockerhub", "linuxserver/sonarr", "latest") is None

    def test_ttl_expiry(self, monkeypatch):
        """After TTL elapses, get must return None and evict the entry."""
        from datetime import UTC, datetime, timedelta

        import app.services.channel_anchor as channel_anchor_module

        cache = AnchorCache(ttl_minutes=5)
        resolution = AnchorResolution(4, "sha256:abc", "build_version", "")
        cache.set("dockerhub", "linuxserver/sonarr", "latest", resolution)

        # Fast-forward 10 minutes past the stored timestamp.
        real_now = datetime.now(UTC)
        future = real_now + timedelta(minutes=10)
        monkeypatch.setattr(
            channel_anchor_module,
            "datetime",
            type("StubDT", (), {"now": staticmethod(lambda tz=None: future)}),
        )
        assert cache.get("dockerhub", "linuxserver/sonarr", "latest") is None


class TestDecideAnchorBound:
    """R1-H2 state machine: fresh anchor never silently raises the bound."""

    def _resolution(self, major: int) -> AnchorResolution:
        return AnchorResolution(
            anchor_major=major,
            digest=f"sha256:dummy{major}",
            source_label="build_version",
            raw_label_value="",
        )

    def test_feature_disabled_returns_no_bound(self):
        decision = decide_anchor_bound(accepted_anchor_major=None, fresh=None)
        assert decision == AnchorDecision(None, None, channel_shift=False)

    def test_first_enable_baselines_to_fresh(self):
        """When accepted is None but fresh resolves, that becomes the implicit bound."""
        fresh = self._resolution(4)
        decision = decide_anchor_bound(accepted_anchor_major=None, fresh=fresh)
        assert decision.upper_major_bound == 4
        assert decision.channel_shift is False
        assert decision.fresh == fresh

    def test_accepted_preserved_when_fresh_fails(self):
        """Resolution failure must not relax the bound."""
        decision = decide_anchor_bound(accepted_anchor_major=4, fresh=None)
        assert decision.upper_major_bound == 4
        assert decision.channel_shift is False

    def test_fresh_equal_keeps_bound(self):
        fresh = self._resolution(4)
        decision = decide_anchor_bound(accepted_anchor_major=4, fresh=fresh)
        assert decision.upper_major_bound == 4
        assert decision.channel_shift is False

    def test_fresh_below_accepted_keeps_bound(self):
        """Anchor moved backward (rebuild, rollback) — keep accepted bound."""
        fresh = self._resolution(3)
        decision = decide_anchor_bound(accepted_anchor_major=4, fresh=fresh)
        assert decision.upper_major_bound == 4
        assert decision.channel_shift is False

    def test_fresh_above_accepted_emits_channel_shift_without_raising_bound(self):
        """R1-H2 core: fresh > accepted MUST emit channel_shift, bound stays at accepted."""
        fresh = self._resolution(5)
        decision = decide_anchor_bound(accepted_anchor_major=4, fresh=fresh)
        assert decision.upper_major_bound == 4  # bound NEVER auto-advances
        assert decision.channel_shift is True
        assert decision.fresh == fresh
