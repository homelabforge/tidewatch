"""Add supply chain anomaly detection support.

Migration: 053
Description: Adds supply chain detection infrastructure:
    - New supply_chain_baselines table for image-level trust baselines
    - Container columns: supply_chain_enabled, supply_chain_sensitivity
    - Update columns: anomaly_score, anomaly_flags, anomaly_held, expected_digest

    All columns are nullable or have defaults, so simple ALTER TABLE is safe.
"""

import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)


async def upgrade() -> None:
    """Add supply chain detection tables and columns."""
    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.execute(text("BEGIN"))

        try:
            # ── New table: supply_chain_baselines ────────────────────
            await conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS supply_chain_baselines (
                        id INTEGER NOT NULL PRIMARY KEY,
                        registry VARCHAR NOT NULL,
                        image VARCHAR NOT NULL,
                        version_track VARCHAR,
                        last_trusted_tag VARCHAR,
                        last_trusted_digest VARCHAR,
                        last_trusted_size_bytes INTEGER,
                        sample_count INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(registry, image, version_track)
                    )
                """)
            )
            logger.info("Created supply_chain_baselines table")

            # ── Container columns ────────────────────────────────────
            container_cols = (await conn.execute(text("PRAGMA table_info(containers)"))).fetchall()
            existing_container_cols = {row[1] for row in container_cols}

            if "supply_chain_enabled" not in existing_container_cols:
                await conn.execute(
                    text("ALTER TABLE containers ADD COLUMN supply_chain_enabled BOOLEAN")
                )
                logger.info("Added containers.supply_chain_enabled")

            if "supply_chain_sensitivity" not in existing_container_cols:
                await conn.execute(
                    text("ALTER TABLE containers ADD COLUMN supply_chain_sensitivity VARCHAR")
                )
                logger.info("Added containers.supply_chain_sensitivity")

            # ── Update columns ───────────────────────────────────────
            update_cols = (await conn.execute(text("PRAGMA table_info(updates)"))).fetchall()
            existing_update_cols = {row[1] for row in update_cols}

            if "anomaly_score" not in existing_update_cols:
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN anomaly_score INTEGER DEFAULT 0")
                )
                logger.info("Added updates.anomaly_score")

            if "anomaly_flags" not in existing_update_cols:
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN anomaly_flags JSON DEFAULT '[]'")
                )
                logger.info("Added updates.anomaly_flags")

            if "anomaly_held" not in existing_update_cols:
                await conn.execute(
                    text("ALTER TABLE updates ADD COLUMN anomaly_held BOOLEAN DEFAULT 0")
                )
                logger.info("Added updates.anomaly_held")

            if "expected_digest" not in existing_update_cols:
                await conn.execute(text("ALTER TABLE updates ADD COLUMN expected_digest VARCHAR"))
                logger.info("Added updates.expected_digest")

            await conn.execute(text("COMMIT"))
            logger.info("Migration 053 complete: supply chain detection support added")

        except Exception:
            await conn.execute(text("ROLLBACK"))
            raise

        await conn.execute(text("PRAGMA foreign_keys=ON"))


async def downgrade() -> None:
    """Downgrade not supported for safety."""
    raise NotImplementedError(
        "Downgrade not supported. Restore from pre-migration backup if needed."
    )
