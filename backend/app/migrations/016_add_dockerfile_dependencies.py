#!/usr/bin/env python3
"""Migration: Add dockerfile_dependencies table for tracking Docker base images.

This migration adds:
1. dockerfile_dependencies table for tracking FROM statements in Dockerfiles
2. Foreign key relationship to containers table
3. Indexes for efficient querying

Created: 2025-11-23
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db import engine


async def upgrade():
    """Apply migration: Create dockerfile_dependencies table."""
    async with engine.begin() as conn:
        print("Creating dockerfile_dependencies table...")

        # Create the table
        await conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS dockerfile_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_id INTEGER NOT NULL,
                dependency_type VARCHAR NOT NULL,
                image_name VARCHAR NOT NULL,
                current_tag VARCHAR NOT NULL,
                registry VARCHAR NOT NULL DEFAULT 'docker.io',
                full_image VARCHAR NOT NULL,
                latest_tag VARCHAR,
                update_available BOOLEAN DEFAULT 0,
                last_checked TIMESTAMP,
                dockerfile_path VARCHAR NOT NULL,
                line_number INTEGER,
                stage_name VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (container_id) REFERENCES containers (id) ON DELETE CASCADE
            )
        """)
        )
        print("✓ Created dockerfile_dependencies table")

        # Create indexes
        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_dockerfile_dependencies_container_id
            ON dockerfile_dependencies(container_id)
        """)
        )
        print("✓ Created index ix_dockerfile_dependencies_container_id")

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_dockerfile_dependencies_dependency_type
            ON dockerfile_dependencies(dependency_type)
        """)
        )
        print("✓ Created index ix_dockerfile_dependencies_dependency_type")

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_dockerfile_dependencies_update_available
            ON dockerfile_dependencies(update_available)
        """)
        )
        print("✓ Created index ix_dockerfile_dependencies_update_available")

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS ix_dockerfile_dependencies_last_checked
            ON dockerfile_dependencies(last_checked)
        """)
        )
        print("✓ Created index ix_dockerfile_dependencies_last_checked")

        print("Migration completed successfully!")


async def downgrade():
    """Rollback migration: Drop dockerfile_dependencies table."""
    async with engine.begin() as conn:
        print("Dropping dockerfile_dependencies table...")

        # Drop indexes (SQLite will drop them automatically with the table, but being explicit)
        await conn.execute(
            text("DROP INDEX IF EXISTS ix_dockerfile_dependencies_container_id")
        )
        await conn.execute(
            text("DROP INDEX IF EXISTS ix_dockerfile_dependencies_dependency_type")
        )
        await conn.execute(
            text("DROP INDEX IF EXISTS ix_dockerfile_dependencies_update_available")
        )
        await conn.execute(
            text("DROP INDEX IF EXISTS ix_dockerfile_dependencies_last_checked")
        )
        print("✓ Dropped indexes")

        # Drop table
        await conn.execute(text("DROP TABLE IF EXISTS dockerfile_dependencies"))
        print("✓ Dropped dockerfile_dependencies table")

        print("Rollback completed!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        print("Running downgrade...")
        asyncio.run(downgrade())
    else:
        print("Running upgrade...")
        asyncio.run(upgrade())
