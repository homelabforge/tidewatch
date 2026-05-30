"""Custom exceptions for TideWatch application."""

from typing import Any


class SSRFProtectionError(Exception):
    """Raised when a URL fails SSRF (Server-Side Request Forgery) validation.

    This exception indicates that a URL was blocked for security reasons,
    either because it points to a private/internal resource (localhost, private IPs,
    cloud metadata endpoints) or violates other SSRF protection policies.

    Used by url_validation.py to prevent attackers from using the application
    to access internal services or sensitive endpoints.
    """

    pass


class OIDCSubjectMismatchError(Exception):
    """Raised when an OIDC login presents a subject that does not match the one
    already bound to the admin account.

    Once an admin account is bound to an OIDC ``sub``, re-login is accepted only
    from that same subject. A different subject (a different identity at the same
    provider) is rejected outright rather than silently rebinding the account —
    this is the closed half of the #1 account-takeover hole. The callback maps
    this to HTTP 403 without leaking the bound identity.
    """

    pass


class PendingLinkRequiredError(Exception):
    """Raised when OIDC linking requires password verification for admin account.

    This exception is raised during OIDC authentication when:
    - Username matches the admin account
    - No OIDC subject link exists yet
    - The admin has a local password (not OIDC-only)

    The exception carries the necessary data to create a pending link token
    and redirect the user to the password verification flow.
    """

    def __init__(
        self,
        username: str,
        claims: dict[str, Any],
        userinfo: dict[str, Any] | None,
        config: dict[str, str],
    ):
        """Initialize the exception with OIDC authentication data.

        Args:
            username: The admin username that requires verification
            claims: ID token claims from the OIDC provider
            userinfo: Optional userinfo endpoint claims
            config: OIDC provider configuration
        """
        self.username = username
        self.claims = claims
        self.userinfo = userinfo
        self.config = config
        super().__init__("Admin account requires password verification for OIDC linking")
