"""Encrypt oidc_client_secret / admin_password_hash at rest and mark them encrypted.

Migration 024 flipped these settings' ``encrypted`` flag to TRUE without
re-encrypting the stored value, and a flag-flip bug then kept un-setting the flag
on every save (the keys were absent from DEFAULTS). With the DEFAULTS fix the flag
now sticks at TRUE — so any row still holding *plaintext* under ``encrypted=TRUE``
would make ``SettingsService.get()`` try to Fernet-decrypt plaintext
(→ InvalidToken → ValueError → None), silently breaking OIDC.

This migration repairs the *data*, not just the flag: it encrypts true-plaintext
values and marks them encrypted, gated on encryption actually being configured.

Two-stage detection (``is_encrypted`` prefix + a confirming ``decrypt``) prevents
both double-encryption and the astronomically-unlikely plaintext-starting-with
"gAAAAA" false positive. Idempotent (genuine ciphertext rows always skip).
Forward-only.

NOTE on the no-op branch: if encryption is unconfigured this is a no-op and is
still marked applied (it won't auto-rerun). The main.py key bootstrap auto-creates
/data/encryption.key on first boot, so this branch only triggers when /data is
unwritable. If you ever run key-less then later add a key manually, re-save the
OIDC secret in the UI to re-encrypt it.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_SECRET_KEYS = ("oidc_client_secret", "admin_password_hash")


async def upgrade(conn) -> None:
    """Encrypt plaintext secret settings and ensure their encrypted flag is set."""
    from app.utils.encryption import get_encryption_service, is_encryption_configured

    if not is_encryption_configured():
        # No key configured: get() never decrypts, so plaintext reads back fine.
        # Leave value + flag untouched.
        logger.warning("Migration 062: encryption not configured; leaving secret settings as-is.")
        return

    svc = get_encryption_service()

    for key in _SECRET_KEYS:
        row = (
            await conn.execute(
                text("SELECT value, encrypted FROM settings WHERE key = :key"),
                {"key": key},
            )
        ).fetchone()
        if row is None:
            continue

        value = row[0]
        if not value:
            # Empty value — nothing to encrypt, just ensure the flag is set.
            await conn.execute(
                text("UPDATE settings SET encrypted = 1 WHERE key = :key"),
                {"key": key},
            )
            continue

        if svc.is_encrypted(value):
            # Prefix says ciphertext — confirm it decrypts under the current key.
            try:
                svc.decrypt(value)
            except ValueError:
                # Prefix matched but wrong key / corrupt: never re-encrypt corrupt
                # data; leave it untouched for manual recovery.
                logger.error(
                    "Migration 062: '%s' looks encrypted but does not decrypt; leaving untouched.",
                    key,
                )
                continue
            # Genuine ciphertext — ensure the flag is set and move on.
            await conn.execute(
                text("UPDATE settings SET encrypted = 1 WHERE key = :key"),
                {"key": key},
            )
            continue

        # True plaintext under (now) encrypted=TRUE — encrypt it.
        encrypted_value = svc.encrypt(value)
        await conn.execute(
            text("UPDATE settings SET value = :value, encrypted = 1 WHERE key = :key"),
            {"value": encrypted_value, "key": key},
        )
        logger.info("Migration 062: encrypted plaintext setting '%s'.", key)


async def downgrade(conn) -> None:
    raise NotImplementedError(
        "Migration 062 is forward-only. Restore from a pre-062 backup if needed."
    )
