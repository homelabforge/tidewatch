"""Repair admin rows poisoned by the pre-#1 OIDC auto-link behavior.

Before the #1 fix, a successful OIDC login from *any* identity at the
configured provider force-set ``auth_method = 'oidc'`` on the admin row even
when no ``oidc_subject`` was actually bound. That permanently disabled
password login (and password rotation) for an account that was never genuinely
linked.

This migration resets such rows back to ``'local'`` — restoring the local
password (the break-glass recovery path) and the change-password flow — while
leaving rows with a genuine, non-empty ``oidc_subject`` untouched.

Idempotent: the predicate-scoped UPDATE is a no-op once the row is ``'local'``.
Forward-only (mirrors the 060 template).
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Reset auth_method='oidc' rows that never bound a subject back to 'local'."""
    await db.execute(
        text(
            "UPDATE users SET auth_method = 'local' "
            "WHERE auth_method = 'oidc' AND (oidc_subject IS NULL OR oidc_subject = '')"
        )
    )


async def downgrade(db) -> None:
    raise NotImplementedError(
        "Migration 061 is forward-only. Restore from a pre-061 backup if needed."
    )
