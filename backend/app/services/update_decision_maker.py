"""Update decision maker - determines if updates are available.

This module extracts the update decision logic from the update checker,
enabling clean separation between tag fetching and decision making.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from app.services.tag_fetcher import FetchTagsResponse
from app.services.update_checker import UpdateDecisionTrace
from app.utils.version import get_version_change_type

if TYPE_CHECKING:
    from app.models.container import Container

logger = logging.getLogger(__name__)


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
    update_kind: Optional[str]  # "tag" or "digest"
    latest_tag: Optional[str]
    latest_major_tag: Optional[str]
    change_type: Optional[str]  # "major", "minor", "patch"
    is_scope_violation: bool
    trace: UpdateDecisionTrace
    digest_changed: bool = False
    new_digest: Optional[str] = None


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
        container: "Container",
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
        current_digest: Optional[str] = container.current_digest  # type: ignore[attr-defined]

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

        # Check for digest-based update (for 'latest' tag)
        digest_changed = False
        new_digest: Optional[str] = None
        if current_tag == "latest" and fetch_response.metadata:
            new_digest = fetch_response.metadata.get("digest")
            if new_digest and current_digest:
                digest_changed = new_digest != current_digest
                trace.set_digest_update(
                    current_digest,
                    new_digest,
                    digest_changed,
                )

        # Determine if there's an in-scope update
        has_update = False
        update_kind: Optional[str] = None
        change_type: Optional[str] = None

        if latest_tag and latest_tag != current_tag:
            has_update = True
            update_kind = "tag"
            change_type = get_version_change_type(current_tag, latest_tag)
            trace.set_tag_update(latest_tag, change_type)
        elif digest_changed:
            has_update = True
            update_kind = "digest"

        # Check for scope violation
        is_scope_violation = False
        if (
            latest_major_tag
            and latest_major_tag != current_tag
            and latest_major_tag != latest_tag
        ):
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
        )

    def _extract_suffix(self, tag: str) -> Optional[str]:
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
