#!/usr/bin/env python3
"""Database migration: Add Intelligent Container Restart Support

This migration adds:
- Restart configuration columns to containers table
- container_restart_state table for tracking restart state
- container_restart_log table for audit trail
- Restart-related settings

Usage:
    python migrations/001_add_intelligent_restart.py
"""

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    columns = result.fetchall()
    return any(col[1] == column for col in columns)


async def check_table_exists(conn, table: str) -> bool:
    """Check if a table exists."""
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table"),
        {"table": table},
    )
    return result.fetchone() is not None


async def migrate():
    """Run the migration."""
    logger.info("Starting migration: Add Intelligent Container Restart Support")
    logger.info(f"Database URL: {DATABASE_URL}")

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            # ================================================================
            # STEP 1: Add restart columns to containers table
            # ================================================================
            logger.info("Step 1: Adding restart columns to containers table...")

            columns_to_add = [
                ("auto_restart_enabled", "BOOLEAN DEFAULT 0"),
                ("restart_policy", "TEXT DEFAULT 'manual'"),
                ("restart_max_attempts", "INTEGER DEFAULT 10"),
                ("restart_backoff_strategy", "TEXT DEFAULT 'exponential'"),
                ("restart_success_window", "INTEGER DEFAULT 300"),
            ]

            for column, definition in columns_to_add:
                if not await check_column_exists(conn, "containers", column):
                    await conn.execute(
                        text(f"ALTER TABLE containers ADD COLUMN {column} {definition}")
                    )
                    logger.info(f"  ✓ Added column: {column}")
                else:
                    logger.info(f"  ⊘ Column already exists: {column}")

            # ================================================================
            # STEP 2: Create container_restart_state table
            # ================================================================
            logger.info("Step 2: Creating container_restart_state table...")

            if not await check_table_exists(conn, "container_restart_state"):
                await conn.execute(
                    text("""
                    CREATE TABLE container_restart_state (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        container_id INTEGER NOT NULL UNIQUE,
                        container_name TEXT NOT NULL,

                        -- Restart tracking
                        consecutive_failures INTEGER DEFAULT 0 NOT NULL,
                        total_restarts INTEGER DEFAULT 0 NOT NULL,
                        last_exit_code INTEGER,
                        last_failure_reason TEXT,

                        -- Backoff state
                        current_backoff_seconds REAL DEFAULT 0.0 NOT NULL,
                        next_retry_at TIMESTAMP,
                        max_retries_reached BOOLEAN DEFAULT 0 NOT NULL,

                        -- Success tracking
                        last_successful_start TIMESTAMP,
                        last_failure_at TIMESTAMP,
                        success_window_seconds INTEGER DEFAULT 300 NOT NULL,

                        -- Configuration (per-container overrides)
                        enabled BOOLEAN DEFAULT 1 NOT NULL,
                        max_attempts INTEGER DEFAULT 10 NOT NULL,
                        backoff_strategy TEXT DEFAULT 'exponential' NOT NULL,
                        base_delay_seconds REAL DEFAULT 2.0 NOT NULL,
                        max_delay_seconds REAL DEFAULT 300.0 NOT NULL,

                        -- Health check configuration
                        health_check_enabled BOOLEAN DEFAULT 1 NOT NULL,
                        health_check_timeout INTEGER DEFAULT 60 NOT NULL,
                        rollback_on_health_fail BOOLEAN DEFAULT 0 NOT NULL,

                        -- Circuit breaker
                        paused_until TIMESTAMP,
                        pause_reason TEXT,

                        -- Metadata
                        restart_history TEXT DEFAULT '[]' NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

                        FOREIGN KEY (container_id) REFERENCES containers (id) ON DELETE CASCADE
                    )
                """)
                )

                # Create indexes
                await conn.execute(
                    text(
                        "CREATE INDEX idx_restart_state_container_id ON container_restart_state(container_id)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_restart_state_container_name ON container_restart_state(container_name)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_restart_state_next_retry ON container_restart_state(next_retry_at)"
                    )
                )

                logger.info("  ✓ Created container_restart_state table with indexes")
            else:
                logger.info("  ⊘ Table already exists: container_restart_state")

            # ================================================================
            # STEP 3: Create container_restart_log table
            # ================================================================
            logger.info("Step 3: Creating container_restart_log table...")

            if not await check_table_exists(conn, "container_restart_log"):
                await conn.execute(
                    text("""
                    CREATE TABLE container_restart_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        container_id INTEGER NOT NULL,
                        container_name TEXT NOT NULL,

                        -- Attempt details
                        attempt_number INTEGER NOT NULL,
                        trigger_reason TEXT NOT NULL,
                        exit_code INTEGER,

                        -- Execution details
                        backoff_delay_seconds REAL NOT NULL,
                        success BOOLEAN NOT NULL,
                        health_check_passed BOOLEAN,
                        error_message TEXT,

                        -- Timestamps
                        scheduled_at TIMESTAMP NOT NULL,
                        executed_at TIMESTAMP NOT NULL,
                        completed_at TIMESTAMP,

                        FOREIGN KEY (container_id) REFERENCES containers (id) ON DELETE CASCADE
                    )
                """)
                )

                # Create indexes
                await conn.execute(
                    text(
                        "CREATE INDEX idx_restart_log_container_id ON container_restart_log(container_id)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_restart_log_scheduled_at ON container_restart_log(scheduled_at)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_restart_log_success ON container_restart_log(success)"
                    )
                )

                logger.info("  ✓ Created container_restart_log table with indexes")
            else:
                logger.info("  ⊘ Table already exists: container_restart_log")

            # ================================================================
            # STEP 4: Create timestamp update trigger
            # ================================================================
            logger.info("Step 4: Creating timestamp update trigger...")

            await conn.execute(
                text("""
                CREATE TRIGGER IF NOT EXISTS update_restart_state_timestamp
                AFTER UPDATE ON container_restart_state
                BEGIN
                    UPDATE container_restart_state
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE id = NEW.id;
                END
            """)
            )
            logger.info("  ✓ Created timestamp update trigger")

            # ================================================================
            # STEP 5: Insert default restart settings
            # ================================================================
            logger.info("Step 5: Adding restart settings...")

            settings = [
                (
                    "restart_monitor_enabled",
                    "true",
                    "restart",
                    "Enable automatic container restart monitoring",
                ),
                (
                    "restart_monitor_interval",
                    "30",
                    "restart",
                    "Interval in seconds to check container health (default: 30)",
                ),
                (
                    "restart_default_strategy",
                    "exponential",
                    "restart",
                    "Default backoff strategy: exponential, linear, or fixed",
                ),
                (
                    "restart_default_max_attempts",
                    "10",
                    "restart",
                    "Default maximum restart attempts before giving up",
                ),
                (
                    "restart_base_delay",
                    "2",
                    "restart",
                    "Base delay in seconds for exponential backoff (default: 2)",
                ),
                (
                    "restart_max_delay",
                    "300",
                    "restart",
                    "Maximum delay in seconds between restart attempts (default: 300)",
                ),
                (
                    "restart_success_window",
                    "300",
                    "restart",
                    "Seconds a container must run successfully to reset failure count (default: 300)",
                ),
                (
                    "restart_health_check_timeout",
                    "60",
                    "restart",
                    "Timeout in seconds for health checks after restart (default: 60)",
                ),
                (
                    "restart_enable_notifications",
                    "true",
                    "restart",
                    "Send ntfy notifications for restart events",
                ),
                (
                    "restart_max_concurrent",
                    "10",
                    "restart",
                    "Maximum number of concurrent restart operations (default: 10)",
                ),
                (
                    "restart_cleanup_interval",
                    "3600",
                    "restart",
                    "Interval in seconds to cleanup old restart state (default: 3600)",
                ),
                (
                    "restart_log_retention_days",
                    "30",
                    "restart",
                    "Number of days to retain restart logs (default: 30)",
                ),
            ]

            for key, value, category, description in settings:
                # Check if setting already exists
                result = await conn.execute(
                    text("SELECT key FROM settings WHERE key = :key"), {"key": key}
                )
                if not result.fetchone():
                    await conn.execute(
                        text("""
                            INSERT INTO settings (key, value, encrypted, category, description)
                            VALUES (:key, :value, 0, :category, :description)
                        """),
                        {
                            "key": key,
                            "value": value,
                            "category": category,
                            "description": description,
                        },
                    )
                    logger.info(f"  ✓ Added setting: {key}")
                else:
                    logger.info(f"  ⊘ Setting already exists: {key}")

            # ================================================================
            # Verification
            # ================================================================
            logger.info("Verifying migration...")

            # Check tables
            result = await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%restart%' ORDER BY name"
                )
            )
            tables = [row[0] for row in result.fetchall()]
            logger.info(f"  Restart tables: {', '.join(tables)}")

            # Check settings
            result = await conn.execute(
                text("SELECT COUNT(*) FROM settings WHERE category = 'restart'")
            )
            setting_count = result.scalar()
            logger.info(f"  Restart settings: {setting_count}")

            logger.info("\n✅ Migration completed successfully!")

    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
