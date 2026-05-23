"""Update decision maker - determines if updates are available.

This module extracts the update decision logic from the update checker,
enabling clean separation between tag fetching and decision making.

Also contains UpdateDecisionTrace which is used by both this module and
update_checker.py for building structured decision traces.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.services.registry_client import is_non_semver_tag
from app.services.tag_fetcher import FetchTagsResponse
from app.utils.version import get_version_change_type

# Phase 3 (D11): slack window for the stale-tag heuristic. A candidate
# pushed within ``STALE_TAG_SLACK`` of the current tag's push time is still
# accepted, to handle harmless backfills (rebuild, mirror sync, etc.).
STALE_TAG_SLACK = timedelta(days=7)

if TYPE_CHECKING:
    from app.models.container import Container

logger = logging.getLogger(__name__)


class UpdateDecisionTrace:
    """Builder for structured update decision trace.

    Captures the reasoning behind update detection decisions for debugging,
    UI explanations, and analytics.
    """

    def __init__(self) -> None:
        self.trace: dict[str, Any] = {
            "update_kind": None,
            "current_tag": None,
            "latest_tag": None,
            "scope": None,
            "change_type": None,
            "include_prereleases": None,
            "suffix_match": None,
            "digest_info": {"previous": None, "current": None, "changed": False},
            "registry": None,
            "scope_blocking": {
                "blocked": False,
                "latest_major_tag": None,
                "reason": None,
            },
            "registry_anomalies": [],
            "decision_timestamp": None,
        }

    def set_basics(
        self,
        current_tag: str,
        scope: str,
        include_prereleases: bool,
        registry: str,
    ) -> None:
        """Set basic context for the update check."""
        self.trace["current_tag"] = current_tag
        self.trace["scope"] = scope
        self.trace["include_prereleases"] = include_prereleases
        self.trace["registry"] = registry

    def set_digest_update(
        self,
        previous: str | None,
        current: str | None,
        changed: bool,
    ) -> None:
        """Record digest-based update detection."""
        self.trace["update_kind"] = "digest"
        self.trace["digest_info"] = {
            "previous": previous[:12] if previous else None,
            "current": current[:12] if current else None,
            "changed": changed,
        }

    def set_tag_update(
        self,
        latest_tag: str | None,
        change_type: str | None,
    ) -> None:
        """Record tag-based update detection."""
        self.trace["update_kind"] = "tag"
        self.trace["latest_tag"] = latest_tag
        self.trace["change_type"] = change_type

    def set_suffix_match(self, suffix: str | None) -> None:
        """Record tag suffix matching (e.g., '-alpine', '-slim')."""
        self.trace["suffix_match"] = suffix

    def set_scope_blocking(
        self,
        blocked: bool,
        latest_major_tag: str | None,
        reason: str | None,
    ) -> None:
        """Record scope blocking decision."""
        self.trace["scope_blocking"] = {
            "blocked": blocked,
            "latest_major_tag": latest_major_tag,
            "reason": reason,
        }

    def add_anomaly(self, anomaly: str) -> None:
        """Record registry anomalies encountered during check."""
        self.trace["registry_anomalies"].append(anomaly)

    def to_json(self) -> str:
        """Serialize trace to JSON string for storage.

        Uses a fallback encoder to handle any non-serializable values
        (e.g., mock objects during testing) by converting them to strings.
        """
        self.trace["decision_timestamp"] = datetime.now(UTC).isoformat()
        return json.dumps(self.trace, default=str)

    @property
    def update_kind(self) -> str | None:
        """Get the determined update kind."""
        return self.trace["update_kind"]

    @property
    def change_type(self) -> str | None:
        """Get the determined change type."""
        return self.trace["change_type"]


@dataclass
class UpdateDecision:
    """Result of update decision analysis.

    Attributes:
        has_update: Whether an update is available within scope
        update_kind: Type of update ("tag" or "digest")
        latest_tag: Latest tag within scope (if update available)
        latest_major_tag: Latest major version (may be blocked by scope)
        change_type: Semver change type ("major", "minor", "patch")
        is_scope_violation: Whether a major update is blocked by scope
        trace: Decision trace for debugging and UI explanation
        digest_changed: Whether digest changed (for 'latest' tag)
        new_digest: New digest value (for 'latest' tag)
    """

    has_update: bool
    update_kind: str | None  # "tag" or "digest"
    latest_tag: str | None
    latest_major_tag: str | None
    change_type: str | None  # "major", "minor", "patch"
    is_scope_violation: bool
    trace: UpdateDecisionTrace
    digest_changed: bool = False
    new_digest: str | None = None
    digest_baseline_needed: bool = False


class UpdateDecisionMaker:
    """Makes update decisions based on fetched tag data.

    Responsibilities:
    - Compare current tag to available tags
    - Determine if update is within scope
    - Detect scope violations (major updates blocked by scope)
    - Build decision trace for debugging

    Does NOT:
    - Fetch tags from registries
    - Modify database records
    - Send notifications

    This is a pure logic class with no I/O operations.

    Example:
        decision_maker = UpdateDecisionMaker()

        # After fetching tags
        fetch_response = await tag_fetcher.fetch_tags(request)

        # Make decision
        decision = decision_maker.make_decision(
            container, fetch_response, include_prereleases
        )

        if decision.has_update:
            # Update available
            print(f"Update: {container.current_tag} -> {decision.latest_tag}")
        elif decision.is_scope_violation:
            # Major update blocked by scope
            print(f"Major update blocked: {decision.latest_major_tag}")
    """

    def make_decision(
        self,
        container: Container,
        fetch_response: FetchTagsResponse,
        include_prereleases: bool,
    ) -> UpdateDecision:
        """Analyze fetched tags and make update decision.

        Args:
            container: Container being checked
            fetch_response: Response from tag fetcher
            include_prereleases: Whether prereleases are included

        Returns:
            UpdateDecision with analysis results
        """
        # Get container attributes (with type: ignore for SQLAlchemy)
        current_tag: str = str(container.current_tag)  # type: ignore[attr-defined]
        scope: str = str(container.scope)  # type: ignore[attr-defined]
        registry: str = str(container.registry)  # type: ignore[attr-defined]
        current_digest: str | None = container.current_digest  # type: ignore[attr-defined]

        # Initialize decision trace
        trace = UpdateDecisionTrace()
        trace.set_basics(
            current_tag=current_tag,
            scope=scope,
            include_prereleases=include_prereleases,
            registry=registry,
        )

        # Handle fetch errors
        if fetch_response.error:
            trace.add_anomaly(f"Fetch error: {fetch_response.error}")
            return UpdateDecision(
                has_update=False,
                update_kind=None,
                latest_tag=None,
                latest_major_tag=None,
                change_type=None,
                is_scope_violation=False,
                trace=trace,
            )

        # Extract suffix from current tag
        suffix = self._extract_suffix(current_tag)
        trace.set_suffix_match(suffix)

        latest_tag = fetch_response.latest_tag
        latest_major_tag = fetch_response.latest_major_tag

        # Check for digest-based update (non-semver tags: latest, lts, stable, etc.)
        digest_changed = False
        digest_baseline_needed = False
        new_digest: str | None = None
        digest_cross_major_shift = False
        if is_non_semver_tag(current_tag) and fetch_response.metadata:
            new_digest = fetch_response.metadata.get("digest")
            if new_digest and current_digest:
                digest_changed = new_digest != current_digest
                trace.set_digest_update(
                    current_digest,
                    new_digest,
                    digest_changed,
                )
                # Phase 6.2: when the digest changed AND we can resolve the
                # new tag's upstream major, compare against the container's
                # stored last_digest_major. A differing major indicates an
                # upstream channel shift on a mutable tag (e.g. linuxserver/sonarr
                # re-pointing `latest` from v4 stable to a v5 build).
                #
                # First-check gap (codex Pass 4): when ``last_digest_major``
                # is NULL on a post-migration container with an existing
                # ``current_digest``, we cannot prove the prior major matched
                # the fresh major. Be conservative and emit channel_shift
                # rather than silently baselining to ``fresh_major`` — the
                # user might be on the very v4→v5 transition we are trying
                # to surface. The trace records ``previous_major=None`` so
                # the UI can explain the unknown prior state.
                fresh_major = getattr(fetch_response, "current_tag_major", None)
                stored_major: int | None = getattr(container, "last_digest_major", None)  # type: ignore[attr-defined]
                if digest_changed and isinstance(fresh_major, int):
                    if isinstance(stored_major, int) and fresh_major != stored_major:
                        digest_cross_major_shift = True
                        trace.trace["digest_channel_shift"] = {
                            "previous_major": stored_major,
                            "new_major": fresh_major,
                            "tag": current_tag,
                        }
                    elif stored_major is None:
                        digest_cross_major_shift = True
                        trace.trace["digest_channel_shift"] = {
                            "previous_major": None,
                            "new_major": fresh_major,
                            "tag": current_tag,
                            "reason": "first_check_unknown_baseline",
                        }
            elif new_digest and current_digest is None:
                # First run: baseline needs to be stored but it's not an "update"
                digest_baseline_needed = True
                trace.set_digest_update(None, new_digest, False)

        # Phase 2 (D10): apply `:latest` lineage cap before promoting a
        # semver candidate. If `:latest` resolves to a major below the
        # candidate's major, the candidate is an orphan-tag suspect and
        # must be rejected unless the container has opted out.
        latest_lineage_major = getattr(fetch_response, "latest_lineage_major", None)
        lineage_cap_disabled = bool(
            getattr(container, "latest_lineage_cap_disabled", False) or False
        )
        if (
            latest_tag
            and latest_tag != current_tag
            and isinstance(latest_lineage_major, int)
            and not lineage_cap_disabled
        ):
            candidate_parsed = self._parse_candidate_major(latest_tag)
            if candidate_parsed is not None and candidate_parsed > latest_lineage_major:
                trace.trace["latest_cap_skip"] = {
                    "candidate_tag": latest_tag,
                    "candidate_major": candidate_parsed,
                    "latest_cap_major": latest_lineage_major,
                    "method": getattr(fetch_response, "latest_lineage_method", None),
                }
                trace.add_anomaly(
                    f"latest_cap_skip: {latest_tag} (major={candidate_parsed}) > "
                    f":latest major={latest_lineage_major}"
                )
                latest_tag = None  # Suppress this candidate for downstream logic.

        # Phase 3 (D11): stale-tag heuristic. If the candidate was pushed
        # well before the current tag, it's almost certainly an orphan /
        # historical artifact — reject unless within slack window.
        latest_pushed_at = getattr(fetch_response, "latest_tag_pushed_at", None)
        current_pushed_at = getattr(fetch_response, "current_tag_pushed_at", None)
        if (
            latest_tag
            and latest_tag != current_tag
            and latest_pushed_at is not None
            and current_pushed_at is not None
            and latest_pushed_at < current_pushed_at - STALE_TAG_SLACK
        ):
            trace.trace["stale_tag_skip"] = {
                "candidate_tag": latest_tag,
                "candidate_pushed_at": latest_pushed_at.isoformat()
                if hasattr(latest_pushed_at, "isoformat")
                else str(latest_pushed_at),
                "current_pushed_at": current_pushed_at.isoformat()
                if hasattr(current_pushed_at, "isoformat")
                else str(current_pushed_at),
            }
            trace.add_anomaly(
                f"stale_tag_skip: candidate {latest_tag} pushed "
                f"{latest_pushed_at} < current {current_pushed_at}"
            )
            latest_tag = None

        # Determine if there's an in-scope update
        has_update = False
        update_kind: str | None = None
        change_type: str | None = None

        if latest_tag and latest_tag != current_tag:
            has_update = True
            update_kind = "tag"
            change_type = get_version_change_type(current_tag, latest_tag)
            trace.set_tag_update(latest_tag, change_type)
        elif digest_changed:
            has_update = True
            # Phase 6.2: a digest change that crosses upstream major
            # boundaries is a channel_shift, not a normal digest update.
            # The user must explicitly accept it via the approval UI.
            if digest_cross_major_shift:
                update_kind = "channel_shift"
                change_type = "major"
                trace.trace["update_kind"] = "channel_shift"
            else:
                update_kind = "digest"

        # Phase 6: surface anchor drift.
        # Channel drift information is always recorded in the trace so the UI
        # and approval flow can see it, but it only becomes the dominant
        # update_kind when there is no in-bound tag/digest update to report.
        # Otherwise the in-bound patch (e.g. 4.0.17.2952 -> 4.0.17.2953) gets
        # suppressed by a channel_shift "update" that has no actual target
        # tag — apply_decision would then create a current_tag -> current_tag
        # phantom update.
        anchor_decision = getattr(fetch_response, "anchor_decision", None)
        if anchor_decision is not None and getattr(anchor_decision, "channel_shift", False):
            fresh = getattr(anchor_decision, "fresh", None)
            new_major = getattr(fresh, "anchor_major", None) if fresh is not None else None
            accepted_major = getattr(anchor_decision, "upper_major_bound", None)
            channel_shift_block = {
                "previous_major": accepted_major,
                "new_major": new_major,
                "anchor_tag": getattr(container, "stable_anchor_tag", None),
                "source_label": getattr(fresh, "source_label", None) if fresh else None,
                "anchor_digest": getattr(fresh, "digest", None) if fresh else None,
                "raw_label_value": (getattr(fresh, "raw_label_value", None) if fresh else None),
            }
            trace.trace["channel_shift"] = channel_shift_block
            trace.add_anomaly(
                f"channel_shift detected: anchor drifted from "
                f"major={accepted_major} to major={new_major}"
            )

            if not has_update:
                # No in-bound tag/digest update — channel_shift becomes the
                # update. apply_decision will need a meaningful target; we
                # signal that by leaving latest_tag as None and letting the
                # approval flow surface the anchor drift to the user.
                has_update = True
                update_kind = "channel_shift"
                change_type = "major"
                trace.trace["update_kind"] = "channel_shift"
            else:
                # An in-bound tag/digest update is the primary surface. Keep
                # its update_kind dominant but mark channel_shift_pending so
                # the UI can render a secondary warning badge.
                trace.trace["channel_shift_pending"] = True

        # Check for scope violation
        is_scope_violation = False
        if latest_major_tag and latest_major_tag != current_tag and latest_major_tag != latest_tag:
            is_scope_violation = True
            trace.set_scope_blocking(
                blocked=True,
                latest_major_tag=latest_major_tag,
                reason=f"scope={scope} blocks major update to {latest_major_tag}",
            )

        return UpdateDecision(
            has_update=has_update,
            update_kind=update_kind,
            latest_tag=latest_tag if has_update and update_kind == "tag" else None,
            latest_major_tag=latest_major_tag,
            change_type=change_type,
            is_scope_violation=is_scope_violation,
            trace=trace,
            digest_changed=digest_changed,
            new_digest=new_digest,
            digest_baseline_needed=digest_baseline_needed,
        )

    @staticmethod
    def _parse_candidate_major(tag: str) -> int | None:
        """Parse a candidate tag's major number using packaging.Version.

        Returns None for tags that can't be parsed (non-semver). Tolerates
        v-prefix and build metadata suffixes.
        """
        from packaging.version import InvalidVersion, Version

        version = tag.lstrip("vV")
        if "+" in version:
            version = version.split("+", 1)[0]
        try:
            parsed = Version(version)
        except InvalidVersion:
            for sep in ("-", "_"):
                if sep in version:
                    base = version.split(sep, 1)[0]
                    try:
                        parsed = Version(base)
                        break
                    except InvalidVersion:
                        continue
            else:
                return None
        if parsed.release:
            return parsed.release[0]
        return None

    def _extract_suffix(self, tag: str) -> str | None:
        """Extract suffix from tag (e.g., '-alpine', '-slim').

        Args:
            tag: Tag string to extract suffix from

        Returns:
            Suffix string (without leading dash) or None
        """
        if "-" in tag:
            parts = tag.split("-", 1)
            if len(parts) > 1 and parts[1] and not parts[1][0].isdigit():
                return parts[1]
        return None
