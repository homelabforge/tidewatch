"""Tests for OIDC account-linking security (link_oidc_to_admin).

Covers the #1 admin-link takeover fix end to end against a real in-memory DB:
- the first link is password-gated (PendingLinkRequiredError, nothing bound),
- a password-verified first link binds the subject and stamps last_login,
- a bound account accepts re-login only from the same subject,
- a different subject is rejected (OIDCSubjectMismatchError) and unchanged,
- a passwordless admin binds on first link without the pending-link detour.
"""

import pytest

from app.exceptions import OIDCSubjectMismatchError, PendingLinkRequiredError
from app.models.user import User
from app.services.auth import _get_admin_user, hash_password
from app.services.oidc import link_oidc_to_admin

CONFIG = {"provider_name": "Test Provider", "username_claim": "preferred_username"}


async def _make_admin(db, *, password_hash="", oidc_subject=None, auth_method="local"):
    user = User(
        username="admin",
        email="admin@example.com",
        password_hash=password_hash,
        auth_method=auth_method,
        oidc_subject=oidc_subject,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


class TestLinkOIDCToAdmin:
    async def test_first_link_with_password_requires_pending(self, db):
        """First link while a local password exists raises PendingLinkRequiredError
        and binds nothing."""
        await _make_admin(db, password_hash=hash_password("Password123!"))
        claims = {"sub": "oidc-user-1", "preferred_username": "admin"}

        with pytest.raises(PendingLinkRequiredError):
            await link_oidc_to_admin(db, claims, None, CONFIG)

        user = await _get_admin_user(db)
        assert user is not None
        assert user.oidc_subject is None
        assert user.auth_method == "local"

    async def test_password_verified_first_link_binds(self, db):
        """A password-verified first link binds the subject and stamps last_login."""
        await _make_admin(db, password_hash=hash_password("Password123!"))
        claims = {"sub": "oidc-user-1", "preferred_username": "admin"}

        await link_oidc_to_admin(db, claims, None, CONFIG, password_verified=True)

        user = await _get_admin_user(db)
        assert user is not None
        assert user.oidc_subject == "oidc-user-1"
        assert user.auth_method == "oidc"
        assert user.oidc_provider == "Test Provider"
        assert user.last_login is not None

    async def test_relogin_matching_sub_ok(self, db):
        """Re-login from the bound subject succeeds without raising."""
        await _make_admin(
            db,
            password_hash=hash_password("Password123!"),
            oidc_subject="oidc-user-1",
            auth_method="oidc",
        )
        claims = {"sub": "oidc-user-1", "preferred_username": "admin"}

        await link_oidc_to_admin(db, claims, None, CONFIG)

        user = await _get_admin_user(db)
        assert user is not None
        assert user.oidc_subject == "oidc-user-1"

    async def test_relogin_mismatched_sub_raises(self, db):
        """A different subject is rejected and the binding is unchanged."""
        await _make_admin(
            db,
            password_hash=hash_password("Password123!"),
            oidc_subject="oidc-user-1",
            auth_method="oidc",
        )
        claims = {"sub": "evil-user-2", "preferred_username": "admin"}

        with pytest.raises(OIDCSubjectMismatchError):
            await link_oidc_to_admin(db, claims, None, CONFIG)

        user = await _get_admin_user(db)
        assert user is not None
        assert user.oidc_subject == "oidc-user-1"

    async def test_no_password_first_time_binds_without_pending(self, db):
        """A passwordless admin binds on first link without the pending-link detour."""
        await _make_admin(db, password_hash="")
        claims = {"sub": "oidc-user-1", "preferred_username": "admin"}

        await link_oidc_to_admin(db, claims, None, CONFIG)

        user = await _get_admin_user(db)
        assert user is not None
        assert user.oidc_subject == "oidc-user-1"
        assert user.auth_method == "oidc"
