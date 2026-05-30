"""Tests for migration 062 (encrypt oidc_client_secret / admin_password_hash).

Covers: plaintext encrypted-then-marked, idempotent (byte-identical second run),
no-op when no key configured, genuine ciphertext skipped, and corrupt
ciphertext-looking values left untouched.
"""

import importlib.util
from pathlib import Path

from sqlalchemy import select

from app.models.setting import Setting

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "migrations"
    / "062_encrypt_oidc_admin_secrets.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_062", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _add_secret(db, value, *, encrypted=True, key="oidc_client_secret"):
    db.add(Setting(key=key, value=value, category="security", encrypted=encrypted))
    await db.commit()


async def _row(db, key="oidc_client_secret"):
    return (await db.execute(select(Setting).where(Setting.key == key))).scalar_one()


class TestMigration062:
    async def test_encrypts_plaintext(self, db):
        from app.utils.encryption import get_encryption_service

        await _add_secret(db, "plaintext-secret")
        await _load_migration().upgrade(db)
        await db.commit()

        row = await _row(db)
        assert row.value.startswith("gAAAAA")
        assert row.encrypted is True
        assert get_encryption_service().decrypt(row.value) == "plaintext-secret"

    async def test_idempotent(self, db):
        await _add_secret(db, "plaintext-secret")
        mig = _load_migration()

        await mig.upgrade(db)
        await db.commit()
        first_value = (await _row(db)).value

        await mig.upgrade(db)
        await db.commit()
        # Genuine ciphertext on the second pass → byte-identical, not re-encrypted.
        assert (await _row(db)).value == first_value

    async def test_noop_when_key_unset(self, db, monkeypatch):
        import app.utils.encryption as enc

        monkeypatch.delenv("TIDEWATCH_ENCRYPTION_KEY", raising=False)
        monkeypatch.setattr(enc, "_encryption_service", None)

        await _add_secret(db, "plaintext-secret")
        await _load_migration().upgrade(db)
        await db.commit()

        # Unconfigured → no-op; value left as plaintext.
        assert (await _row(db)).value == "plaintext-secret"

    async def test_skips_already_ciphertext(self, db):
        from app.utils.encryption import get_encryption_service

        ciphertext = get_encryption_service().encrypt("already-secret")
        await _add_secret(db, ciphertext)

        await _load_migration().upgrade(db)
        await db.commit()

        assert (await _row(db)).value == ciphertext

    async def test_leaves_corrupt_untouched(self, db):
        corrupt = "gAAAAA" + "garbagegarbage"
        await _add_secret(db, corrupt)

        await _load_migration().upgrade(db)
        await db.commit()

        # Prefix matched but decrypt fails → never re-encrypt corrupt data.
        assert (await _row(db)).value == corrupt

    async def test_empty_value_sets_flag_only(self, db):
        await _add_secret(db, "", encrypted=False)

        await _load_migration().upgrade(db)
        await db.commit()

        row = await _row(db)
        assert row.value == ""
        assert row.encrypted is True
