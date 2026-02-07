"""Add decision traceability fields to updates table.

Migration: 035
Date: 2026-01-23
Description: Add decision_trace, update_kind, and change_type columns to track
             the reasoning behind update detection decisions. This enables
             debugging, UI explanations for scope-blocked updates, and analytics.

Fields added:
- decision_trace: JSON string containing structured trace of all decision points
- update_kind: "tag" or "digest" - distinguishes update type
- change_type: "major", "minor", "patch" - semver change classification
"""

from sqlalchemy import text


async def up(db):
    """Add decision traceability fields to updates table."""
    # Check if columns exist before adding (idempotent)
    result = await db.execute(text("PRAGMA table_info(updates)"))
    columns = {row[1] for row in result.fetchall()}

    if "decision_trace" not in columns:
        await db.execute(text("ALTER TABLE updates ADD COLUMN decision_trace TEXT DEFAULT NULL"))

    if "update_kind" not in columns:
        await db.execute(text("ALTER TABLE updates ADD COLUMN update_kind TEXT DEFAULT NULL"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_update_kind ON updates(update_kind)"))

    if "change_type" not in columns:
        await db.execute(text("ALTER TABLE updates ADD COLUMN change_type TEXT DEFAULT NULL"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_change_type ON updates(change_type)"))

    # No explicit commit needed — runner's engine.begin() handles it


async def down(db):  # noqa: ARG001
    """Remove decision traceability fields from updates table."""
    # SQLite doesn't support DROP COLUMN directly in older versions
    # For now, just document this limitation
    raise NotImplementedError("Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
