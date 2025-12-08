"""Custom exceptions for TideWatch application."""

from typing import Any, Dict, Optional


class SSRFProtectionError(Exception):
    """Raised when a URL fails SSRF (Server-Side Request Forgery) validation.

    This exception indicates that a URL was blocked for security reasons,
    either because it points to a private/internal resource (localhost, private IPs,
    cloud metadata endpoints) or violates other SSRF protection policies.

    Used by url_validation.py to prevent attackers from using the application
    to access internal services or sensitive endpoints.
    """
    pass


class PendingLinkRequiredException(Exception):
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
        claims: Dict[str, Any],
        userinfo: Optional[Dict[str, Any]],
        config: Dict[str, str],
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
        super().__init__(
            f"Admin account requires password verification for OIDC linking"
        )
