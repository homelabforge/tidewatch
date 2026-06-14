"""Backfill vuln_scanned_at for containers that were already scanned.

Migration: 064
Description: Migration 063 added vuln_scanned_at as NULL for every existing row.
             On upgrade that makes every container render "Not scanned" until the
             next scheduled VulnForge baseline refresh re-stamps it (up to the
             check interval, default 6h) — alarming when a container previously
             showed real vulnerability counts.

             Any container with current_vuln_count > 0 was demonstrably scanned
             (you cannot have vulnerabilities without a successful VulnForge
             match), so backfill its vuln_scanned_at from last_checked (the check
             that set the count), falling back to now.

             Rows with current_vuln_count = 0 are deliberately left NULL: 0 is
             ambiguous between "scanned clean" and "never matched" (e.g. My
             Projects with local/empty image refs), and the next check re-confirms
             genuinely-clean containers as scanned. Idempotent (only touches NULL
             stamps) and forward-only.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Stamp vuln_scanned_at for containers that already carry a vuln count."""
    await db.execute(
        text(
            "UPDATE containers "
            "SET vuln_scanned_at = COALESCE(last_checked, CURRENT_TIMESTAMP) "
            "WHERE current_vuln_count > 0 AND vuln_scanned_at IS NULL"
        )
    )


async def downgrade(db) -> None:  # noqa: ARG001
    """Forward-only: clearing the backfilled timestamps is not meaningful."""
    raise NotImplementedError("Migration 064 is forward-only.")
