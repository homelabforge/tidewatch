"""Fix CVE tracking JSON defaults and backfill historical data

This migration fixes a SQLAlchemy JSON column bug where Column(JSON, default=list)
creates a shared mutable default, causing CVE data to not be properly transferred
from the 'updates' table to the 'update_history' table.

Changes:
1. Add server_default='[]' to cves_fixed columns in both tables
2. Backfill empty cves_fixed in update_history from corresponding updates records

Revision ID: 023
Revises: 022
"""

import sqlite3
from pathlib import Path


def get_db_path() -> str:
    """Get the database path from environment or default location."""
    import os
    db_path = os.getenv("DATABASE_PATH")
    if db_path:
        return db_path

    # Default path in production
    prod_path = "/data/tidewatch.db"
    if Path(prod_path).exists():
        return prod_path

    # Development path
    return str(Path(__file__).parent.parent.parent / "tidewatch.db")


async def upgrade():
    """Apply the migration."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Starting migration 023: Fix CVE tracking JSON defaults")

        # Step 1: Add server defaults to cves_fixed columns
        # Note: SQLite doesn't support ALTER COLUMN to add DEFAULT
        # The server_default will be enforced at the SQLAlchemy level
        # (already updated in the models)

        # Step 2: Backfill historical data - copy CVE data from updates to update_history
        print("Backfilling CVE data from updates to update_history...")

        # First, check how many records need updating
        cursor.execute("""
            SELECT COUNT(*)
            FROM update_history
            WHERE update_id IS NOT NULL
              AND (cves_fixed IS NULL OR cves_fixed = '[]')
              AND EXISTS (
                  SELECT 1 FROM updates
                  WHERE updates.id = update_history.update_id
                    AND updates.cves_fixed IS NOT NULL
                    AND updates.cves_fixed != '[]'
              )
        """)
        count = cursor.fetchone()[0]
        print(f"Found {count} update_history records with missing CVE data")

        # Perform the backfill
        cursor.execute("""
            UPDATE update_history
            SET cves_fixed = (
                SELECT updates.cves_fixed
                FROM updates
                WHERE updates.id = update_history.update_id
            )
            WHERE update_history.update_id IS NOT NULL
              AND (update_history.cves_fixed IS NULL OR update_history.cves_fixed = '[]')
              AND EXISTS (
                  SELECT 1 FROM updates
                  WHERE updates.id = update_history.update_id
                    AND updates.cves_fixed IS NOT NULL
                    AND updates.cves_fixed != '[]'
              )
        """)

        affected = cursor.rowcount
        print(f"Backfilled {affected} update_history records with CVE data")

        # Verify the backfill
        cursor.execute("""
            SELECT uh.id, uh.container_name, uh.to_tag, uh.cves_fixed
            FROM update_history uh
            JOIN updates u ON uh.update_id = u.id
            WHERE uh.cves_fixed != '[]'
              AND uh.completed_at >= datetime('now', '-30 days')
            ORDER BY uh.completed_at DESC
            LIMIT 5
        """)

        results = cursor.fetchall()
        if results:
            print(f"\nRecent update_history records with CVE data:")
            for row in results:
                import json
                cve_count = len(json.loads(row[3])) if row[3] else 0
                print(f"  ID {row[0]}: {row[1]} → {row[2]} ({cve_count} CVEs)")

        conn.commit()
        print("Migration 023 completed successfully")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        conn.close()


def downgrade():
    """Revert the migration (no-op for data backfill)."""
    print("Downgrade for migration 023 is a no-op (server defaults removed at SQLAlchemy level)")
    print("Note: We don't reverse the CVE data backfill as it represents corrected historical data")


if __name__ == "__main__":
    print("Running migration 023...")
    upgrade()
