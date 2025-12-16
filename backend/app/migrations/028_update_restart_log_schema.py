#!/usr/bin/env python3
"""Database migration: Update container_restart_log table schema

This migration adds missing columns to the container_restart_log table
to match the current ContainerRestartLog model.

Missing columns:
- restart_state_id (FK to container_restart_state)
- failure_reason (detailed failure description)
- backoff_strategy (strategy used for this attempt)
- restart_method (docker_compose or docker_restart)
- docker_command (actual command executed)
- duration_seconds (execution duration)
- health_check_enabled (whether health check was enabled)
- health_check_duration (health check duration)
- health_check_method (http or docker_inspect)
- health_check_error (health check error message)
- final_container_status (container status after restart)
- final_exit_code (exit code after restart)
- created_at (timestamp when log entry was created)

Usage:
    python migrations/007_update_restart_log_schema.py
"""

import sys
import asyncio
import logging
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    result = await conn.execute(
        text(f"PRAGMA table_info({table})")
    )
    columns = result.fetchall()
    return any(col[1] == column for col in columns)


async def migrate():
    """Run the migration."""
    logger.info("Starting migration: Update container_restart_log schema")
    logger.info(f"Database URL: {DATABASE_URL}")

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            logger.info("Adding missing columns to container_restart_log table...")

            columns_to_add = [
                ("restart_state_id", "INTEGER"),
                ("failure_reason", "TEXT"),
                ("backoff_strategy", "TEXT NOT NULL DEFAULT 'exponential'"),
                ("restart_method", "TEXT NOT NULL DEFAULT 'docker_compose'"),
                ("docker_command", "TEXT"),
                ("duration_seconds", "REAL"),
                ("health_check_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                ("health_check_duration", "REAL"),
                ("health_check_method", "TEXT"),
                ("health_check_error", "TEXT"),
                ("final_container_status", "TEXT"),
                ("final_exit_code", "INTEGER"),
                ("created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ]

            added_count = 0
            for column, definition in columns_to_add:
                if not await check_column_exists(conn, "container_restart_log", column):
                    await conn.execute(
                        text(f"ALTER TABLE container_restart_log ADD COLUMN {column} {definition}")
                    )
                    logger.info(f"  ✓ Added column: {column}")
                    added_count += 1
                else:
                    logger.info(f"  ⊘ Column already exists: {column}")

            if added_count > 0:
                logger.info(f"\n✅ Migration completed successfully! Added {added_count} columns.")
            else:
                logger.info("\n✅ Migration already applied (all columns exist).")

            # Verify all columns exist
            logger.info("\nVerifying migration...")
            result = await conn.execute(
                text("PRAGMA table_info(container_restart_log)")
            )
            columns = result.fetchall()
            logger.info(f"  Total columns in container_restart_log: {len(columns)}")

            # Check for critical columns
            critical_columns = ["restart_state_id", "failure_reason", "backoff_strategy",
                               "restart_method", "health_check_enabled"]
            missing = []
            for col in critical_columns:
                if not any(c[1] == col for c in columns):
                    missing.append(col)

            if missing:
                logger.error(f"  ❌ Missing critical columns: {', '.join(missing)}")
            else:
                logger.info("  ✓ All critical columns present")

    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
