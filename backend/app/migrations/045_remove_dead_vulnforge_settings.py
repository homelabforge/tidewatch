"""Remove dead vulnforge_username and vulnforge_password settings.

Migration: 045
Date: 2026-02-09
Description: Cleans up legacy basic_auth settings that are no longer supported.
             VulnForge only accepts X-API-Key authentication. These settings were
             left behind when basic_auth support was removed in Phase 1.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade() -> None:
    """Remove dead vulnforge basic_auth settings."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM settings WHERE key IN ('vulnforge_username', 'vulnforge_password')")
        )
        deleted = result.rowcount
        if deleted:
            # Log is informational only — migration is idempotent
            pass


async def downgrade() -> None:
    """No-op: cannot restore deleted credentials."""
    pass
