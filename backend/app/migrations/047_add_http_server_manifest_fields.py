"""Add manifest context fields to http_servers.

Stores the manifest file path, package name, and ecosystem for HTTP servers
detected via dependency files (pyproject.toml, requirements.txt, package.json).
This enables the update mechanism to modify the actual source file instead of
looking for a nonexistent LABEL in the Dockerfile.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def upgrade(connection):
    """Add manifest_file, package_name, and ecosystem columns."""
    result = await connection.execute(text("PRAGMA table_info(http_servers)"))
    columns = {row[1] for row in result.fetchall()}

    if "manifest_file" not in columns:
        await connection.execute(text("ALTER TABLE http_servers ADD COLUMN manifest_file VARCHAR"))
        logger.info("  Added column 'manifest_file'")
    else:
        logger.info("  -> Column 'manifest_file' already exists, skipping")

    if "package_name" not in columns:
        await connection.execute(text("ALTER TABLE http_servers ADD COLUMN package_name VARCHAR"))
        logger.info("  Added column 'package_name'")
    else:
        logger.info("  -> Column 'package_name' already exists, skipping")

    if "ecosystem" not in columns:
        await connection.execute(text("ALTER TABLE http_servers ADD COLUMN ecosystem VARCHAR"))
        logger.info("  Added column 'ecosystem'")
    else:
        logger.info("  -> Column 'ecosystem' already exists, skipping")


async def downgrade(connection):
    """SQLite does not support DROP COLUMN before 3.35.0; log only."""
    logger.info(
        "  Downgrade: manifest_file, package_name, and ecosystem "
        "columns left in place (SQLite limitation)"
    )
