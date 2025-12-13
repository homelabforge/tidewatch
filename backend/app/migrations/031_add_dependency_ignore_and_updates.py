"""Add dependency ignore tracking and file update support.

Migration: 031
Date: 2025-01-28
Description:
    - Creates http_servers table for persistent HTTP server tracking
    - Creates app_dependencies table for application dependency tracking
    - Adds ignore tracking fields to dockerfile_dependencies table
    - Adds dependency event fields to update_history table
    - Enables ignore/unignore functionality with smart version reset
    - Supports file-based dependency updates through UI
"""

from sqlalchemy import text


async def up(db):
    """Add dependency ignore and update support."""

    # ===================================================================
    # Part 1: Create http_servers table
    # ===================================================================
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS http_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_id INTEGER NOT NULL,

            -- Server details
            name VARCHAR NOT NULL,
            current_version VARCHAR,
            latest_version VARCHAR,
            update_available BOOLEAN DEFAULT 0 NOT NULL,
            severity VARCHAR DEFAULT 'info' NOT NULL,
            detection_method VARCHAR NOT NULL,

            -- Dockerfile context
            dockerfile_path VARCHAR,
            line_number INTEGER,

            -- Ignore tracking (version-specific)
            ignored BOOLEAN DEFAULT 0 NOT NULL,
            ignored_version VARCHAR,
            ignored_by VARCHAR,
            ignored_at DATETIME,
            ignored_reason TEXT,

            -- Metadata
            last_checked DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            version INTEGER DEFAULT 1 NOT NULL,

            FOREIGN KEY (container_id) REFERENCES containers(id)
        )
    """))

    # Create indexes for http_servers
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_http_servers_container_id ON http_servers (container_id)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_http_servers_name ON http_servers (name)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_http_servers_update_available ON http_servers (update_available)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_http_servers_ignored ON http_servers (ignored)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_http_servers_last_checked ON http_servers (last_checked)"))

    # ===================================================================
    # Part 2: Create app_dependencies table
    # ===================================================================
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS app_dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_id INTEGER NOT NULL,

            -- Dependency details
            name VARCHAR NOT NULL,
            ecosystem VARCHAR NOT NULL,
            current_version VARCHAR NOT NULL,
            latest_version VARCHAR,
            update_available BOOLEAN DEFAULT 0 NOT NULL,
            dependency_type VARCHAR DEFAULT 'production' NOT NULL,

            -- Security and quality
            security_advisories INTEGER DEFAULT 0,
            socket_score REAL,
            severity VARCHAR DEFAULT 'info' NOT NULL,

            -- File location
            manifest_file VARCHAR NOT NULL,

            -- Ignore tracking (version-specific)
            ignored BOOLEAN DEFAULT 0 NOT NULL,
            ignored_version VARCHAR,
            ignored_by VARCHAR,
            ignored_at DATETIME,
            ignored_reason TEXT,

            -- Metadata
            last_checked DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            version INTEGER DEFAULT 1 NOT NULL,

            FOREIGN KEY (container_id) REFERENCES containers(id)
        )
    """))

    # Create indexes for app_dependencies
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_app_dependencies_container_id ON app_dependencies (container_id)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_app_dependencies_name ON app_dependencies (name)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_app_dependencies_ecosystem ON app_dependencies (ecosystem)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_app_dependencies_update_available ON app_dependencies (update_available)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_app_dependencies_ignored ON app_dependencies (ignored)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_app_dependencies_last_checked ON app_dependencies (last_checked)"))

    # ===================================================================
    # Part 3: Add ignore fields to dockerfile_dependencies table
    # ===================================================================
    # Check existing columns first (idempotent)
    result = await db.execute(text("PRAGMA table_info(dockerfile_dependencies)"))
    columns = {row[1] for row in result.fetchall()}

    if "ignored" not in columns:
        await db.execute(text("ALTER TABLE dockerfile_dependencies ADD COLUMN ignored BOOLEAN DEFAULT 0 NOT NULL"))
    if "ignored_version" not in columns:
        await db.execute(text("ALTER TABLE dockerfile_dependencies ADD COLUMN ignored_version VARCHAR"))
    if "ignored_by" not in columns:
        await db.execute(text("ALTER TABLE dockerfile_dependencies ADD COLUMN ignored_by VARCHAR"))
    if "ignored_at" not in columns:
        await db.execute(text("ALTER TABLE dockerfile_dependencies ADD COLUMN ignored_at DATETIME"))
    if "ignored_reason" not in columns:
        await db.execute(text("ALTER TABLE dockerfile_dependencies ADD COLUMN ignored_reason TEXT"))
    if "version" not in columns:
        await db.execute(text("ALTER TABLE dockerfile_dependencies ADD COLUMN version INTEGER DEFAULT 1 NOT NULL"))

    # Create index for ignored column
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_dockerfile_dependencies_ignored ON dockerfile_dependencies (ignored)"))

    # ===================================================================
    # Part 4: Add dependency event fields to update_history table
    # ===================================================================
    # Check existing columns first (idempotent)
    result = await db.execute(text("PRAGMA table_info(update_history)"))
    columns = {row[1] for row in result.fetchall()}

    if "event_type" not in columns:
        await db.execute(text("ALTER TABLE update_history ADD COLUMN event_type VARCHAR"))
    if "dependency_type" not in columns:
        await db.execute(text("ALTER TABLE update_history ADD COLUMN dependency_type VARCHAR"))
    if "dependency_id" not in columns:
        await db.execute(text("ALTER TABLE update_history ADD COLUMN dependency_id INTEGER"))
    if "dependency_name" not in columns:
        await db.execute(text("ALTER TABLE update_history ADD COLUMN dependency_name VARCHAR"))
    if "file_path" not in columns:
        await db.execute(text("ALTER TABLE update_history ADD COLUMN file_path VARCHAR"))

    # Create index for dependency_id column
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_update_history_dependency_id ON update_history (dependency_id)"))

    await db.commit()


async def down(db):
    """Remove dependency ignore and update support (partial - SQLite limitations)."""
    # SQLite doesn't support DROP COLUMN directly
    # We can drop tables but not individual columns without recreating the entire table

    # Drop new tables
    await db.execute(text("DROP TABLE IF EXISTS http_servers"))
    await db.execute(text("DROP TABLE IF EXISTS app_dependencies"))

    # Note: Cannot remove columns from dockerfile_dependencies and update_history without table recreation
    # Those columns will remain but be unused if downgrade is performed

    await db.commit()
