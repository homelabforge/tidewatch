"""Tests for migration 061 (OIDC link-method repair).

Verifies the predicate-scoped repair: poisoned rows (auth_method='oidc' with no
bound subject) are reset to 'local', genuine links are left alone, and re-running
is a no-op.
"""

import importlib.util
from pathlib import Path

from sqlalchemy import select

from app.models.user import User

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "migrations" / "061_oidc_link_method_repair.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_061", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestMigration061:
    async def test_resets_poisoned_null_subject(self, db):
        db.add(
            User(
                username="admin",
                email="a@example.com",
                password_hash="hash",
                auth_method="oidc",
                oidc_subject=None,
            )
        )
        await db.commit()

        await _load_migration().upgrade(db)
        await db.commit()

        user = (await db.execute(select(User))).scalar_one()
        assert user.auth_method == "local"

    async def test_resets_poisoned_empty_subject(self, db):
        db.add(
            User(
                username="admin",
                email="a@example.com",
                password_hash="hash",
                auth_method="oidc",
                oidc_subject="",
            )
        )
        await db.commit()

        await _load_migration().upgrade(db)
        await db.commit()

        user = (await db.execute(select(User))).scalar_one()
        assert user.auth_method == "local"

    async def test_leaves_genuine_link_untouched(self, db):
        db.add(
            User(
                username="admin",
                email="a@example.com",
                password_hash="hash",
                auth_method="oidc",
                oidc_subject="real-subject-123",
            )
        )
        await db.commit()

        await _load_migration().upgrade(db)
        await db.commit()

        user = (await db.execute(select(User))).scalar_one()
        assert user.auth_method == "oidc"
        assert user.oidc_subject == "real-subject-123"

    async def test_idempotent(self, db):
        db.add(
            User(
                username="admin",
                email="a@example.com",
                password_hash="hash",
                auth_method="oidc",
                oidc_subject=None,
            )
        )
        await db.commit()

        module = _load_migration()
        await module.upgrade(db)
        await db.commit()
        await module.upgrade(db)  # second run is a no-op
        await db.commit()

        user = (await db.execute(select(User))).scalar_one()
        assert user.auth_method == "local"
