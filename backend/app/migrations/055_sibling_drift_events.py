"""Add sibling drift events table.

Migration: 055
Description: Append-only audit trail for sibling drift detection.
    Records one row per check run per drifted sibling group.
"""

import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    """Create sibling_drift_events table."""
    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.execute(text("BEGIN"))

        try:
            await conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS sibling_drift_events (
                        id INTEGER NOT NULL PRIMARY KEY,
                        compose_file VARCHAR NOT NULL,
                        registry VARCHAR NOT NULL,
                        image VARCHAR NOT NULL,
                        sibling_names VARCHAR NOT NULL,
                        dominant_tag VARCHAR NOT NULL,
                        per_container_tags VARCHAR NOT NULL,
                        settings_divergent BOOLEAN NOT NULL DEFAULT 0,
                        reconciliation_attempted BOOLEAN NOT NULL DEFAULT 0,
                        reconciled_names VARCHAR,
                        job_id INTEGER,
                        detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )

            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_drift_detected_at "
                    "ON sibling_drift_events(detected_at)"
                )
            )

            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_drift_image ON sibling_drift_events(image)")
            )

            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_drift_job_id ON sibling_drift_events(job_id)")
            )

            await conn.execute(text("COMMIT"))
            logger.info("Migration 055 complete: sibling drift events table created")

        except Exception:
            await conn.execute(text("ROLLBACK"))
            raise

        await conn.execute(text("PRAGMA foreign_keys=ON"))


async def downgrade() -> None:
    """Downgrade not supported for safety."""
    raise NotImplementedError(
        "Downgrade not supported. Restore from pre-migration backup if needed."
    )
