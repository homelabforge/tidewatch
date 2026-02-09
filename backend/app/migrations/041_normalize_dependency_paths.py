"""Normalize dependency paths to be project-relative.

Migration: 041
Date: 2026-02-08
Description: Strip leading /projects/ prefix from stored paths in
    dockerfile_dependencies, http_servers, and app_dependencies tables.
    Paths should be stored relative to projects_directory setting.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


async def upgrade():
    """Normalize absolute paths to project-relative paths."""
    async with engine.begin() as conn:
        # Normalize DockerfileDependency paths: strip leading /projects/ prefix
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM dockerfile_dependencies "
                "WHERE dockerfile_path LIKE '/projects/%'"
            )
        )
        count = result.scalar() or 0
        if count > 0:
            await conn.execute(
                text(
                    "UPDATE dockerfile_dependencies "
                    "SET dockerfile_path = REPLACE(dockerfile_path, '/projects/', '') "
                    "WHERE dockerfile_path LIKE '/projects/%'"
                )
            )
            print(f"  Normalized {count} dockerfile_dependencies paths")
        else:
            print("  dockerfile_dependencies: no absolute paths found, skipping")

        # Normalize HttpServer paths
        result = await conn.execute(
            text("SELECT COUNT(*) FROM http_servers WHERE dockerfile_path LIKE '/projects/%'")
        )
        count = result.scalar() or 0
        if count > 0:
            await conn.execute(
                text(
                    "UPDATE http_servers "
                    "SET dockerfile_path = REPLACE(dockerfile_path, '/projects/', '') "
                    "WHERE dockerfile_path LIKE '/projects/%'"
                )
            )
            print(f"  Normalized {count} http_servers paths")
        else:
            print("  http_servers: no absolute paths found, skipping")

        # Normalize AppDependency manifest_file paths
        result = await conn.execute(
            text("SELECT COUNT(*) FROM app_dependencies WHERE manifest_file LIKE '/projects/%'")
        )
        count = result.scalar() or 0
        if count > 0:
            await conn.execute(
                text(
                    "UPDATE app_dependencies "
                    "SET manifest_file = REPLACE(manifest_file, '/projects/', '') "
                    "WHERE manifest_file LIKE '/projects/%'"
                )
            )
            print(f"  Normalized {count} app_dependencies paths")
        else:
            print("  app_dependencies: no absolute paths found, skipping")

        # Verification: report any remaining absolute paths
        for table, col in [
            ("dockerfile_dependencies", "dockerfile_path"),
            ("http_servers", "dockerfile_path"),
            ("app_dependencies", "manifest_file"),
        ]:
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE '/%'"))
            remaining = result.scalar() or 0
            if remaining:
                print(f"  WARNING: {remaining} rows in {table}.{col} still have absolute paths")
            else:
                print(f"  OK: {table}.{col} — all paths normalized")


async def downgrade():
    """Cannot reliably restore original absolute paths."""
    print("  Downgrade not supported (original paths not preserved)")
