"""Add foreign key constraints to updates and update_history tables.

Migration: 050
Description: Rebuilds both tables to add proper FOREIGN KEY constraints.
    - updates.container_id → containers(id) ON DELETE CASCADE
    - update_history.container_id → containers(id) ON DELETE SET NULL (nullable)

    SQLite cannot ALTER TABLE to add constraints, so this does a full
    table rebuild: create new table, copy data, drop old, rename.

    Orphaned rows (container_id not in containers.id) are cleaned up:
    - updates: orphaned rows deleted (transient state)
    - update_history: orphaned container_id set to NULL (audit trail preserved)

    NOTE: This is an old-style migration (no parameters) because SQLite
    requires PRAGMA foreign_keys=OFF before table rebuilds, and that pragma
    cannot be changed inside a transaction. The migration runner's
    engine.begin() wrapper would prevent this, so we manage our own connection.
"""

import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    """Rebuild updates and update_history with FK constraints."""
    # SQLite requires PRAGMA foreign_keys=OFF for table rebuilds when other
    # tables have FK references to the table being dropped (pending_scan_jobs
    # references updates). This pragma MUST be set outside any transaction.
    async with engine.connect() as conn:
        # Disable FK enforcement BEFORE starting the transaction
        await conn.execute(text("PRAGMA foreign_keys=OFF"))

        # Now begin an explicit transaction for the rebuild
        await conn.execute(text("BEGIN"))

        try:
            # ── Step 1: Audit orphans ────────────────────────────────
            orphan_updates = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM updates "
                        "WHERE container_id NOT IN (SELECT id FROM containers)"
                    )
                )
            ).scalar_one()

            orphan_history = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM update_history "
                        "WHERE container_id NOT IN (SELECT id FROM containers)"
                    )
                )
            ).scalar_one()

            if orphan_updates:
                logger.warning("Found %d orphaned update rows — will be deleted", orphan_updates)
            if orphan_history:
                logger.warning(
                    "Found %d orphaned update_history rows — container_id will be set to NULL",
                    orphan_history,
                )

            # Also check metrics_history for orphans (pre-existing debt)
            orphan_metrics = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM metrics_history "
                        "WHERE container_id NOT IN (SELECT id FROM containers)"
                    )
                )
            ).scalar_one()

            if orphan_metrics:
                logger.warning(
                    "Found %d orphaned metrics_history rows — will be deleted",
                    orphan_metrics,
                )

            # ── Step 2: Clean up orphans before rebuild ──────────────
            if orphan_metrics:
                await conn.execute(
                    text(
                        "DELETE FROM metrics_history "
                        "WHERE container_id NOT IN (SELECT id FROM containers)"
                    )
                )
                logger.info("Deleted %d orphaned metrics_history rows", orphan_metrics)

            if orphan_updates:
                await conn.execute(
                    text(
                        "DELETE FROM updates WHERE container_id NOT IN (SELECT id FROM containers)"
                    )
                )
                logger.info("Deleted %d orphaned update rows", orphan_updates)

            if orphan_history:
                await conn.execute(
                    text(
                        "UPDATE update_history SET container_id = NULL "
                        "WHERE container_id NOT IN (SELECT id FROM containers)"
                    )
                )
                logger.info(
                    "Nulled container_id on %d orphaned update_history rows", orphan_history
                )

            # ── Step 3: Rebuild update_history ───────────────────────
            await conn.execute(
                text("""
                    CREATE TABLE update_history_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        container_id INTEGER NULL
                            REFERENCES containers(id) ON DELETE SET NULL,
                        container_name VARCHAR NOT NULL,
                        update_id INTEGER NULL,
                        from_tag VARCHAR NOT NULL,
                        to_tag VARCHAR NOT NULL,
                        update_type VARCHAR NULL,
                        backup_path VARCHAR NULL,
                        data_backup_id VARCHAR NULL,
                        data_backup_status VARCHAR NULL,
                        status VARCHAR NOT NULL,
                        error_message TEXT NULL,
                        duration_seconds INTEGER NULL,
                        reason TEXT NULL,
                        reason_type VARCHAR NOT NULL DEFAULT 'unknown',
                        reason_summary TEXT NULL,
                        triggered_by VARCHAR DEFAULT 'system',
                        cves_fixed JSON DEFAULT '[]',
                        can_rollback BOOLEAN DEFAULT 1,
                        rolled_back_at DATETIME NULL,
                        event_type VARCHAR NULL,
                        dependency_type VARCHAR NULL,
                        dependency_id INTEGER NULL,
                        dependency_name VARCHAR NULL,
                        file_path VARCHAR NULL,
                        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        completed_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )

            await conn.execute(
                text("""
                    INSERT INTO update_history_new (
                        id, container_id, container_name, update_id,
                        from_tag, to_tag, update_type, backup_path,
                        data_backup_id, data_backup_status,
                        status, error_message, duration_seconds,
                        reason, reason_type, reason_summary, triggered_by, cves_fixed,
                        can_rollback, rolled_back_at,
                        event_type, dependency_type, dependency_id,
                        dependency_name, file_path,
                        started_at, completed_at, created_at
                    )
                    SELECT
                        id, container_id, container_name, update_id,
                        from_tag, to_tag, update_type, backup_path,
                        data_backup_id, data_backup_status,
                        status, error_message, duration_seconds,
                        reason, reason_type, reason_summary, triggered_by, cves_fixed,
                        can_rollback, rolled_back_at,
                        event_type, dependency_type, dependency_id,
                        dependency_name, file_path,
                        started_at, completed_at, created_at
                    FROM update_history
                """)
            )

            await conn.execute(text("DROP TABLE update_history"))
            await conn.execute(text("ALTER TABLE update_history_new RENAME TO update_history"))

            # Recreate indexes for update_history
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS ix_update_history_container_id ON update_history(container_id)",
                "CREATE INDEX IF NOT EXISTS ix_update_history_container_name ON update_history(container_name)",
                "CREATE INDEX IF NOT EXISTS ix_update_history_update_id ON update_history(update_id)",
                "CREATE INDEX IF NOT EXISTS idx_update_history_status ON update_history(status)",
                "CREATE INDEX IF NOT EXISTS idx_update_history_created_at ON update_history(created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_update_history_started_at ON update_history(started_at DESC)",
                "CREATE INDEX IF NOT EXISTS ix_update_history_dependency_id ON update_history(dependency_id)",
                "CREATE INDEX IF NOT EXISTS idx_update_history_event_type ON update_history(event_type)",
            ]:
                await conn.execute(text(idx_sql))

            logger.info("Rebuilt update_history table with FK constraint (ON DELETE SET NULL)")

            # ── Step 4: Rebuild updates ──────────────────────────────
            await conn.execute(
                text("""
                    CREATE TABLE updates_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        container_id INTEGER NOT NULL
                            REFERENCES containers(id) ON DELETE CASCADE,
                        container_name VARCHAR NOT NULL,
                        from_tag VARCHAR NOT NULL,
                        to_tag VARCHAR NOT NULL,
                        registry VARCHAR NOT NULL,
                        reason_type VARCHAR NOT NULL,
                        reason_summary TEXT NULL,
                        recommendation VARCHAR NULL,
                        changelog TEXT NULL,
                        changelog_url VARCHAR NULL,
                        cves_fixed JSON DEFAULT '[]',
                        current_vulns INTEGER DEFAULT 0,
                        new_vulns INTEGER DEFAULT 0,
                        vuln_delta INTEGER DEFAULT 0,
                        published_date DATETIME NULL,
                        image_size_delta INTEGER DEFAULT 0,
                        status VARCHAR DEFAULT 'pending',
                        scope_violation INTEGER NOT NULL DEFAULT 0,
                        approved_by VARCHAR NULL,
                        approved_at DATETIME NULL,
                        rejected_by VARCHAR NULL,
                        rejected_at DATETIME NULL,
                        rejection_reason TEXT NULL,
                        retry_count INTEGER DEFAULT 0,
                        max_retries INTEGER DEFAULT 3,
                        next_retry_at DATETIME NULL,
                        last_error TEXT NULL,
                        backoff_multiplier INTEGER DEFAULT 3,
                        snoozed_until DATETIME NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        decision_trace TEXT NULL,
                        update_kind VARCHAR NULL,
                        change_type VARCHAR NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )

            await conn.execute(
                text("""
                    INSERT INTO updates_new (
                        id, container_id, container_name,
                        from_tag, to_tag, registry,
                        reason_type, reason_summary, recommendation,
                        changelog, changelog_url,
                        cves_fixed, current_vulns, new_vulns, vuln_delta,
                        published_date, image_size_delta,
                        status, scope_violation,
                        approved_by, approved_at,
                        rejected_by, rejected_at, rejection_reason,
                        retry_count, max_retries, next_retry_at,
                        last_error, backoff_multiplier,
                        snoozed_until, version,
                        decision_trace, update_kind, change_type,
                        created_at, updated_at
                    )
                    SELECT
                        id, container_id, container_name,
                        from_tag, to_tag, registry,
                        reason_type, reason_summary, recommendation,
                        changelog, changelog_url,
                        cves_fixed, current_vulns, new_vulns, vuln_delta,
                        published_date, image_size_delta,
                        status, scope_violation,
                        approved_by, approved_at,
                        rejected_by, rejected_at, rejection_reason,
                        retry_count, max_retries, next_retry_at,
                        last_error, backoff_multiplier,
                        snoozed_until, version,
                        decision_trace, update_kind, change_type,
                        created_at, updated_at
                    FROM updates
                """)
            )

            await conn.execute(text("DROP TABLE updates"))
            await conn.execute(text("ALTER TABLE updates_new RENAME TO updates"))

            # Recreate indexes for updates
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS ix_updates_container_id ON updates(container_id)",
                "CREATE INDEX IF NOT EXISTS ix_updates_container_name ON updates(container_name)",
                "CREATE INDEX IF NOT EXISTS idx_updates_status ON updates(status)",
                "CREATE INDEX IF NOT EXISTS idx_updates_created_at ON updates(created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_updates_snoozed_until ON updates(snoozed_until)",
                "CREATE INDEX IF NOT EXISTS idx_update_lookup ON updates(container_id, from_tag, to_tag, status)",
                "CREATE INDEX IF NOT EXISTS idx_updates_status_version ON updates(status, version)",
                "CREATE INDEX IF NOT EXISTS idx_update_kind ON updates(update_kind)",
                "CREATE INDEX IF NOT EXISTS idx_change_type ON updates(change_type)",
                "CREATE INDEX IF NOT EXISTS idx_updates_container_status ON updates(container_id, status)",
            ]:
                await conn.execute(text(idx_sql))

            logger.info("Rebuilt updates table with FK constraint (ON DELETE CASCADE)")

            # Commit the rebuild transaction
            await conn.execute(text("COMMIT"))

        except Exception:
            await conn.execute(text("ROLLBACK"))
            raise

        # Re-enable FK enforcement and verify integrity
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        # Verify FK integrity on the tables we touched
        for tbl in ("updates", "update_history", "metrics_history"):
            violations = (await conn.execute(text(f"PRAGMA foreign_key_check({tbl})"))).fetchall()
            if violations:
                logger.error("FK violations in %s after rebuild: %d rows", tbl, len(violations))
                raise RuntimeError(f"FK check failed on {tbl}: {len(violations)} violations")

        logger.info("Foreign key check passed for updates, update_history, and metrics_history")


async def downgrade() -> None:
    """Downgrade not supported — table rebuilds are not reversible without backup."""
    raise NotImplementedError(
        "Downgrade not supported. Restore from pre-migration backup if needed."
    )
