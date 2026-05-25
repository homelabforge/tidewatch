"""Add ``oidc_states.code_verifier`` column for PKCE S256.

The OIDC login flow now generates a PKCE ``code_verifier`` at
authorization time and stores it alongside the state so the callback
handler can send it in the token exchange (RFC 7636). The column is
nullable so any in-flight states issued before the upgrade complete
cleanly — those rows simply skip the PKCE leg.
"""

from sqlalchemy import text


async def upgrade(db) -> None:
    """Add code_verifier column to oidc_states (idempotent)."""
    # SQLite-specific column check via PRAGMA. The other targets we support
    # (none in TideWatch — SQLite-only) would need their own path.
    result = await db.execute(text("PRAGMA table_info(oidc_states)"))
    columns = {row[1] for row in result.fetchall()}
    if "code_verifier" in columns:
        return
    await db.execute(text("ALTER TABLE oidc_states ADD COLUMN code_verifier VARCHAR(128)"))


async def downgrade(db) -> None:
    raise NotImplementedError(
        "Migration 060 is forward-only. Restore from a pre-060 backup if needed."
    )
