"""Add composite and dependency table indexes for query performance.

Migration: 038
Date: 2026-02-05
Description: Add composite indexes for frequent multi-column queries and
    ensure dependency table indexes exist for ignored/update_available filtering.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade():
    """Add composite and dependency table indexes."""
    async with engine.begin() as conn:
        # Composite indexes for frequent multi-column queries
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_updates_container_status "
                "ON updates(container_id, status)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_app_dependencies_container_update "
                "ON app_dependencies(container_id, update_available)"
            )
        )

        # Dependency table single-column indexes (may already exist from model index=True,
        # but IF NOT EXISTS ensures idempotency for databases created before index=True was added)
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_app_dependencies_ignored "
                "ON app_dependencies(ignored)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_dockerfile_dependencies_ignored "
                "ON dockerfile_dependencies(ignored)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_dockerfile_dependencies_container_id "
                "ON dockerfile_dependencies(container_id)"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_http_servers_ignored ON http_servers(ignored)")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_http_servers_container_id "
                "ON http_servers(container_id)"
            )
        )

        # UpdateHistory event_type index (deferred column, not indexed by model)
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_update_history_event_type "
                "ON update_history(event_type)"
            )
        )


async def downgrade():
    """Remove indexes."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS idx_update_history_event_type"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_http_servers_container_id"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_http_servers_ignored"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_dockerfile_dependencies_container_id"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_dockerfile_dependencies_ignored"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_app_dependencies_ignored"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_app_dependencies_container_update"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_updates_container_status"))
