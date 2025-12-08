"""Add webhooks table for external event notifications."""

from sqlalchemy import text


async def upgrade(db):
    """Create webhooks table."""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            secret TEXT NOT NULL,
            events TEXT NOT NULL DEFAULT '[]',
            enabled INTEGER NOT NULL DEFAULT 1,
            retry_count INTEGER NOT NULL DEFAULT 3,
            last_triggered DATETIME,
            last_status TEXT,
            last_error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # Create index on name for faster lookups
    await db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_webhooks_name
        ON webhooks(name)
    """))

    # Create index on enabled for filtering active webhooks
    await db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_webhooks_enabled
        ON webhooks(enabled)
    """))

    await db.commit()


async def downgrade(db):
    """Drop webhooks table."""
    await db.execute(text("DROP INDEX IF EXISTS idx_webhooks_enabled"))
    await db.execute(text("DROP INDEX IF EXISTS idx_webhooks_name"))
    await db.execute(text("DROP TABLE IF EXISTS webhooks"))
    await db.commit()
