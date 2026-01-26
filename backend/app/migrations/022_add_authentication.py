#!/usr/bin/env python3
"""Database migration: Add Authentication Support

This migration adds:
- oidc_states table for OAuth2 state/nonce tracking
- oidc_pending_links table for password verification during account linking
- Authentication-related settings (auth_mode, admin profile, OIDC config)

Usage:
    python migrations/022_add_authentication.py
"""

import sys
import asyncio
import logging
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_table_exists(conn, table: str) -> bool:
    """Check if a table exists."""
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table"),
        {"table": table},
    )
    return result.fetchone() is not None


async def migrate():
    """Run the migration."""
    logger.info("Starting migration: Add Authentication Support")
    logger.info(f"Database URL: {DATABASE_URL}")

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        async with engine.begin() as conn:
            # ================================================================
            # STEP 1: Create oidc_states table
            # ================================================================
            logger.info("Step 1: Creating oidc_states table...")

            if not await check_table_exists(conn, "oidc_states"):
                await conn.execute(
                    text("""
                    CREATE TABLE oidc_states (
                        state TEXT PRIMARY KEY NOT NULL,
                        nonce TEXT NOT NULL,
                        redirect_uri TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        expires_at TIMESTAMP NOT NULL
                    )
                """)
                )

                # Create index for cleanup operations
                await conn.execute(
                    text(
                        "CREATE INDEX idx_oidc_states_expires_at ON oidc_states(expires_at)"
                    )
                )

                logger.info("  ✓ Created oidc_states table with indexes")
            else:
                logger.info("  ⊘ Table already exists: oidc_states")

            # ================================================================
            # STEP 2: Create oidc_pending_links table
            # ================================================================
            logger.info("Step 2: Creating oidc_pending_links table...")

            if not await check_table_exists(conn, "oidc_pending_links"):
                await conn.execute(
                    text("""
                    CREATE TABLE oidc_pending_links (
                        token TEXT PRIMARY KEY NOT NULL,
                        username TEXT NOT NULL,
                        oidc_claims TEXT NOT NULL,
                        userinfo_claims TEXT,
                        provider_name TEXT NOT NULL,
                        attempt_count INTEGER DEFAULT 0 NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        expires_at TIMESTAMP NOT NULL
                    )
                """)
                )

                # Create indexes
                await conn.execute(
                    text(
                        "CREATE INDEX idx_oidc_pending_links_username ON oidc_pending_links(username)"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE INDEX idx_oidc_pending_links_expires_at ON oidc_pending_links(expires_at)"
                    )
                )

                logger.info("  ✓ Created oidc_pending_links table with indexes")
            else:
                logger.info("  ⊘ Table already exists: oidc_pending_links")

            # ================================================================
            # STEP 3: Insert authentication settings
            # ================================================================
            logger.info("Step 3: Adding authentication settings...")

            settings = [
                # Auth mode
                (
                    "auth_mode",
                    "none",
                    "security",
                    "Authentication mode (none, local, oidc)",
                    False,
                ),
                # Admin profile
                ("admin_username", "", "security", "Administrator username", False),
                ("admin_email", "", "security", "Administrator email address", False),
                (
                    "admin_password_hash",
                    "",
                    "security",
                    "Administrator password hash (Argon2)",
                    True,
                ),
                ("admin_full_name", "", "security", "Administrator full name", False),
                (
                    "admin_auth_method",
                    "local",
                    "security",
                    "Admin authentication method (local or oidc)",
                    False,
                ),
                (
                    "admin_oidc_subject",
                    "",
                    "security",
                    "Admin OIDC subject (sub claim)",
                    False,
                ),
                (
                    "admin_oidc_provider",
                    "",
                    "security",
                    "Admin OIDC provider name",
                    False,
                ),
                (
                    "admin_created_at",
                    "",
                    "security",
                    "Timestamp when admin account was created",
                    False,
                ),
                (
                    "admin_last_login",
                    "",
                    "security",
                    "Timestamp of last admin login",
                    False,
                ),
                # OIDC/SSO configuration
                (
                    "oidc_enabled",
                    "false",
                    "security",
                    "Enable OIDC/SSO authentication",
                    False,
                ),
                (
                    "oidc_provider_name",
                    "",
                    "security",
                    "OIDC provider name (e.g., Authentik, Keycloak)",
                    False,
                ),
                ("oidc_issuer_url", "", "security", "OIDC issuer/discovery URL", False),
                ("oidc_client_id", "", "security", "OIDC client ID", False),
                ("oidc_client_secret", "", "security", "OIDC client secret", True),
                (
                    "oidc_redirect_uri",
                    "",
                    "security",
                    "OIDC redirect URI (auto-generated if empty)",
                    False,
                ),
                (
                    "oidc_scopes",
                    "openid profile email",
                    "security",
                    "OIDC scopes to request (space-separated)",
                    False,
                ),
                (
                    "oidc_username_claim",
                    "preferred_username",
                    "security",
                    "OIDC claim to use for username",
                    False,
                ),
                (
                    "oidc_email_claim",
                    "email",
                    "security",
                    "OIDC claim to use for email address",
                    False,
                ),
                (
                    "oidc_link_token_expire_minutes",
                    "5",
                    "security",
                    "Pending link token expiry in minutes",
                    False,
                ),
                (
                    "oidc_link_max_password_attempts",
                    "3",
                    "security",
                    "Max password attempts for account linking",
                    False,
                ),
            ]

            for key, value, category, description, encrypted in settings:
                # Check if setting already exists
                result = await conn.execute(
                    text("SELECT key FROM settings WHERE key = :key"), {"key": key}
                )
                if not result.fetchone():
                    await conn.execute(
                        text("""
                            INSERT INTO settings (key, value, encrypted, category, description)
                            VALUES (:key, :value, :encrypted, :category, :description)
                        """),
                        {
                            "key": key,
                            "value": value,
                            "encrypted": 1 if encrypted else 0,
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
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%oidc%' ORDER BY name"
                )
            )
            tables = [row[0] for row in result.fetchall()]
            logger.info(f"  OIDC tables: {', '.join(tables)}")

            # Check auth settings
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM settings WHERE key LIKE 'auth_%' OR key LIKE 'admin_%' OR key LIKE 'oidc_%'"
                )
            )
            setting_count = result.scalar()
            logger.info(f"  Auth settings: {setting_count}")

            logger.info("\n✅ Migration completed successfully!")

    except Exception as e:
        logger.error(f"\n❌ Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
