#!/usr/bin/env python3
"""Migration: Mark sensitive settings as encrypted in database.

This migration updates the 'encrypted' flag for sensitive settings that should
be encrypted at rest. This is a security enhancement to protect:
- API keys (Docker Hub, GitHub, VulnForge)
- Authentication tokens (notification services)
- Passwords (SMTP, VulnForge)
- Webhook URLs (may contain secrets)

Note: This migration only marks settings as encrypted. Actual encryption happens
when values are updated through SettingsService if TIDEWATCH_ENCRYPTION_KEY is configured.

Created: 2025-12-06
Version: 3.4.0
Security: Addresses CodeQL finding - Clear Text Storage of Sensitive Data
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db import engine


# List of sensitive setting keys that should be encrypted
SENSITIVE_SETTINGS = [
    # Registry credentials
    "dockerhub_token",
    "ghcr_token",
    # VulnForge integration
    "vulnforge_api_key",
    "vulnforge_password",
    # Notification service tokens
    "ntfy_token",
    "gotify_token",
    "pushover_user_key",
    "pushover_api_token",
    "slack_webhook_url",
    "discord_webhook_url",
    "telegram_bot_token",
    # Email/SMTP
    "email_smtp_password",
    # OIDC (if present - may be added later)
    "oidc_client_secret",
    # Admin (if present - stored separately from DEFAULTS)
    "admin_password_hash",
]


async def upgrade():
    """Apply migration: Mark sensitive settings as encrypted."""
    async with engine.begin() as conn:
        print("Marking sensitive settings as encrypted...")
        print(f"Settings to mark: {len(SENSITIVE_SETTINGS)}")
        print("")

        marked_count = 0
        skipped_count = 0

        for setting_key in SENSITIVE_SETTINGS:
            # Check if setting exists
            result = await conn.execute(
                text("SELECT key, encrypted FROM settings WHERE key = :key"),
                {"key": setting_key},
            )
            setting = result.fetchone()

            if setting:
                # Check if already marked as encrypted
                if setting[1]:  # encrypted column
                    print(f"⏭️  Skipped {setting_key} (already encrypted)")
                    skipped_count += 1
                else:
                    # Mark as encrypted
                    await conn.execute(
                        text("UPDATE settings SET encrypted = TRUE WHERE key = :key"),
                        {"key": setting_key},
                    )
                    print(f"✓ Marked {setting_key} as encrypted")
                    marked_count += 1
            else:
                # Setting doesn't exist yet - will be created with encrypted flag when set
                print(f"⏭️  Skipped {setting_key} (not present in database yet)")
                skipped_count += 1

        print("")
        print("Migration completed successfully!")
        print(f"  Marked: {marked_count}")
        print(f"  Skipped: {skipped_count}")
        print("")
        print("⚠️  IMPORTANT: Values are NOT encrypted by this migration.")
        print("   Existing values remain in plain text until re-saved.")
        print(
            "   Configure TIDEWATCH_ENCRYPTION_KEY and update sensitive settings in UI."
        )


async def downgrade():
    """Rollback migration: Unmark sensitive settings."""
    async with engine.begin() as conn:
        print("Unmarking sensitive settings...")

        unmarked_count = 0

        for setting_key in SENSITIVE_SETTINGS:
            # Unmark as encrypted
            result = await conn.execute(
                text("UPDATE settings SET encrypted = FALSE WHERE key = :key"),
                {"key": setting_key},
            )
            if result.rowcount > 0:
                print(f"✓ Unmarked {setting_key}")
                unmarked_count += 1

        print("")
        print(f"Rollback completed! Unmarked {unmarked_count} settings.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "down":
        print("Running downgrade...")
        asyncio.run(downgrade())
    else:
        print("Running upgrade...")
        asyncio.run(upgrade())
