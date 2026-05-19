"""Add stable-channel-anchor columns to containers table.

Migration: 057
Description: Phase 5 of update-detection-hardening — opt-in per-container
             "stable channel anchor" that prevents cross-major beta promotion
             on images like linuxserver/sonarr where v5 is the upstream beta
             line while v4 is stable.

             - stable_anchor_tag: tag name to resolve as the upper-major
               anchor (typically "latest"). None = feature disabled.
             - accepted_anchor_major: the last user-acknowledged anchor
               major. Fresh upward drift in the registry never auto-advances
               this; Phase 6 surfaces drift as a channel_shift update kind.
             - last_digest_major: for digest-tracked mutable tags (e.g.
               container on `latest`), the major associated with the last
               successful check, used to detect cross-major shifts.

             All three columns are nullable and default to NULL — existing
             containers remain on prior behavior until the user opts in.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Add stable_anchor_tag, accepted_anchor_major, last_digest_major columns."""
    result = await db.execute(text("PRAGMA table_info(containers)"))
    columns = {row[1] for row in result.fetchall()}

    if "stable_anchor_tag" not in columns:
        await db.execute(
            text("ALTER TABLE containers ADD COLUMN stable_anchor_tag VARCHAR(255) NULL")
        )
    if "accepted_anchor_major" not in columns:
        await db.execute(
            text("ALTER TABLE containers ADD COLUMN accepted_anchor_major INTEGER NULL")
        )
    if "last_digest_major" not in columns:
        await db.execute(text("ALTER TABLE containers ADD COLUMN last_digest_major INTEGER NULL"))


async def downgrade(db) -> None:  # noqa: ARG001
    """Downgrade not supported for SQLite ALTER TABLE ADD COLUMN."""
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
