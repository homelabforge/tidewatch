"""Create users table and migrate admin data from settings.

Migration: 051
Description: Creates a proper users table for admin account management.
    Migrates existing admin_* settings keys into the users table.
    Old settings keys are preserved for rollback safety but no longer read.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def upgrade(db) -> None:
    """Create users table and migrate admin data from settings."""
    # ── Step 1: Create users table ─────────────────────────────────────
    await db.execute(
        text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR NOT NULL UNIQUE,
                email VARCHAR NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL DEFAULT '',
                full_name VARCHAR NOT NULL DEFAULT '',
                auth_method VARCHAR NOT NULL DEFAULT 'local',
                oidc_subject VARCHAR NULL,
                oidc_provider VARCHAR NULL,
                last_login DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    )
    logger.info("Created users table")

    # ── Step 2: Check if admin data exists in settings ─────────────────
    result = await db.execute(text("SELECT value FROM settings WHERE key = 'admin_username'"))
    row = result.first()
    admin_username = row[0] if row else None

    if not admin_username or not admin_username.strip():
        logger.info("No admin account in settings — skipping data migration")
        return

    # ── Step 3: Check if user already exists (idempotency) ─────────────
    existing = await db.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {"username": admin_username},
    )
    if existing.first():
        logger.info("Admin user already exists in users table — skipping migration")
        return

    # ── Step 4: Read admin settings ────────────────────────────────────
    async def get_setting(key: str, default: str = "") -> str:
        result = await db.execute(
            text("SELECT value FROM settings WHERE key = :key"),
            {"key": key},
        )
        row = result.first()
        return row[0] if row and row[0] else default

    email = await get_setting("admin_email")
    password_hash = await get_setting("admin_password_hash")
    full_name = await get_setting("admin_full_name")
    auth_method = await get_setting("admin_auth_method", "local")
    oidc_subject = await get_setting("admin_oidc_subject")
    oidc_provider = await get_setting("admin_oidc_provider")
    created_at = await get_setting("admin_created_at")
    last_login = await get_setting("admin_last_login")

    # ── Step 5: Insert into users table ────────────────────────────────
    await db.execute(
        text("""
            INSERT INTO users (
                username, email, password_hash, full_name,
                auth_method, oidc_subject, oidc_provider,
                last_login, created_at
            ) VALUES (
                :username, :email, :password_hash, :full_name,
                :auth_method, :oidc_subject, :oidc_provider,
                :last_login, :created_at
            )
        """),
        {
            "username": admin_username,
            "email": email,
            "password_hash": password_hash,
            "full_name": full_name,
            "auth_method": auth_method,
            "oidc_subject": oidc_subject or None,
            "oidc_provider": oidc_provider or None,
            "last_login": last_login or None,
            "created_at": created_at or None,
        },
    )

    logger.info("Migrated admin account '%s' from settings to users table", admin_username)


async def downgrade(db) -> None:  # noqa: ARG001
    """Downgrade not supported — admin data preserved in settings for rollback."""
    raise NotImplementedError("Downgrade not supported. Admin data still exists in settings table.")
