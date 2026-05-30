"""Tests for SettingsService secret-encryption behavior (#3).

The secret keys are now in DEFAULTS with encrypted:True, so set() keeps the
encrypted flag set instead of silently flipping it back to False (which had stored
plaintext and undone migrations 022/024).
"""

from sqlalchemy import select

from app.models.setting import Setting
from app.services.settings_service import SettingsService


class TestEncryptedDefaults:
    def test_secret_keys_marked_encrypted_in_defaults(self):
        for key in ("oidc_client_secret", "admin_password_hash"):
            assert SettingsService.DEFAULTS[key]["encrypted"] is True

    def test_sensitive_keys_includes_secret_keys(self):
        keys = SettingsService.sensitive_keys()
        assert "oidc_client_secret" in keys
        assert "admin_password_hash" in keys


class TestSetEncryption:
    async def test_roundtrip_through_get(self, db):
        await SettingsService.set(db, "oidc_client_secret", "secret-roundtrip-123")

        row = (
            await db.execute(select(Setting).where(Setting.key == "oidc_client_secret"))
        ).scalar_one()
        assert row.encrypted is True
        assert row.value.startswith("gAAAAA")
        assert row.value != "secret-roundtrip-123"
        assert await SettingsService.get(db, "oidc_client_secret") == "secret-roundtrip-123"

    async def test_flag_not_downgraded_on_resave(self, db):
        await SettingsService.set(db, "oidc_client_secret", "first-secret-value")
        await SettingsService.set(db, "oidc_client_secret", "second-secret-value")

        row = (
            await db.execute(select(Setting).where(Setting.key == "oidc_client_secret"))
        ).scalar_one()
        assert row.encrypted is True
        assert row.value.startswith("gAAAAA")
        assert await SettingsService.get(db, "oidc_client_secret") == "second-secret-value"
