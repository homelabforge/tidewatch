"""OIDC/OpenID Connect authentication service for TideWatch (single-user mode).

This service handles OAuth2/OIDC authentication flow with support for:
- Generic OIDC provider support (Authentik, Keycloak, Auth0, Okta, etc.)
- Account linking to single admin user
- Provider metadata discovery
- Token validation and user info retrieval
- SSRF protection for all external URLs
"""

import logging
import secrets
import json
from typing import Optional, Dict, Any
from datetime import datetime, timezone

import httpx
from authlib.jose import jwt, JsonWebKey, JoseError
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oidc_state import OIDCState
from app.models.oidc_pending_link import OIDCPendingLink
from app.services.settings_service import SettingsService
from app.utils.url_validation import validate_oidc_url
from app.exceptions import SSRFProtectionError
from app.utils.security import sanitize_log_message, mask_sensitive

logger = logging.getLogger(__name__)


def mask_secret(secret: str, show_chars: int = 4) -> str:
    """Mask a secret value for safe logging.

    Shows only the first and last few characters of a secret,
    masking the middle portion. This allows for debugging while
    protecting sensitive data from log exposure.

    Args:
        secret: The secret string to mask
        show_chars: Number of characters to show at start and end (default: 4)

    Returns:
        Masked string in format "abc****...****xyz"

    Examples:
        >>> mask_secret("very_secret_client_id_12345")
        "very****...****2345"
        >>> mask_secret("short")
        "****"
    """
    if not secret or len(secret) <= show_chars * 2:
        return "****"
    return f"{secret[:show_chars]}****...****{secret[-show_chars:]}"


def is_masked_secret(secret: str) -> bool:
    """Detect if a secret value is already masked for display.

    Accepts both the legacy "***" mask and the newer "****...****"
    pattern returned by mask_secret().
    """
    if not secret:
        return False
    return secret.startswith("***") or "****...****" in secret


# ============================================================================
# Cleanup Functions
# ============================================================================


async def _cleanup_expired_states(db: AsyncSession):
    """Remove expired OIDC states from database (older than 10 minutes).

    Args:
        db: Database session
    """
    cutoff = datetime.now(timezone.utc)
    await db.execute(
        delete(OIDCState).where(OIDCState.expires_at <= cutoff)
    )
    await db.commit()


async def _cleanup_expired_pending_links(db: AsyncSession):
    """Remove expired pending link tokens from database.

    Args:
        db: Database session
    """
    cutoff = datetime.now(timezone.utc)
    await db.execute(
        delete(OIDCPendingLink).where(OIDCPendingLink.expires_at <= cutoff)
    )
    await db.commit()


# ============================================================================
# Configuration
# ============================================================================


async def get_oidc_config(db: AsyncSession) -> Dict[str, str]:
    """Get OIDC configuration from database settings.

    Returns:
        Dictionary with OIDC configuration values
    """
    config = {}
    keys = [
        "oidc_enabled",
        "oidc_issuer_url",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_provider_name",
        "oidc_scopes",
        "oidc_redirect_uri",
        "oidc_username_claim",
        "oidc_email_claim",
        "oidc_link_token_expire_minutes",
        "oidc_link_max_password_attempts",
    ]

    for key in keys:
        value = await SettingsService.get(db, key, default="")
        # Remove 'oidc_' prefix for cleaner keys
        clean_key = key.replace("oidc_", "")
        config[clean_key] = value

    return config


# ============================================================================
# Provider Discovery
# ============================================================================


async def get_provider_metadata(issuer_url: str) -> Optional[Dict[str, Any]]:
    """Fetch OIDC provider metadata from well-known endpoint.

    Args:
        issuer_url: OIDC issuer URL

    Returns:
        Provider metadata dictionary or None if fetch fails

    Raises:
        SSRFProtectionError: If issuer_url fails SSRF validation
    """
    # Ensure issuer URL doesn't have trailing slash
    issuer_url = issuer_url.rstrip("/")

    # SECURITY: Validate issuer URL against SSRF attacks (CWE-918)
    try:
        validate_oidc_url(issuer_url)
    except (SSRFProtectionError, ValueError) as e:
        logger.error("SSRF protection blocked OIDC issuer URL: %s - %s", mask_sensitive(issuer_url, visible_chars=20), str(e))
        raise SSRFProtectionError(f"Invalid OIDC issuer URL: {e}")

    # Try standard OIDC discovery endpoint
    discovery_url = f"{issuer_url}/.well-known/openid-configuration"

    # SECURITY: Validate discovery URL as well (defense in depth)
    try:
        validate_oidc_url(discovery_url)
    except (SSRFProtectionError, ValueError) as e:
        logger.error("SSRF protection blocked OIDC discovery URL: %s - %s", mask_sensitive(discovery_url, visible_chars=20), str(e))
        raise SSRFProtectionError(f"Invalid OIDC discovery URL: {e}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(discovery_url, timeout=10.0)
            response.raise_for_status()
            metadata = response.json()

            logger.info("Successfully fetched OIDC metadata from %s", mask_sensitive(discovery_url, visible_chars=20))
            return metadata

    except httpx.TimeoutException:
        logger.error("OIDC metadata request timeout: %s", mask_sensitive(discovery_url, visible_chars=20))
        return None
    except httpx.ConnectError as e:
        logger.error("Cannot connect to OIDC provider: %s: %s", mask_sensitive(discovery_url, visible_chars=20), str(e))
        return None
    except httpx.HTTPStatusError as e:
        logger.error("OIDC provider returned error: %s", str(e))
        return None


# ============================================================================
# State Management
# ============================================================================


def generate_state() -> str:
    """Generate a secure random state parameter for OIDC flow.

    Returns:
        Random state string (32 bytes = 256 bits)
    """
    return secrets.token_urlsafe(32)


async def store_oidc_state(db: AsyncSession, state: str, redirect_uri: str, nonce: str):
    """Store OIDC state in database for validation after callback.

    Args:
        db: Database session
        state: State parameter
        redirect_uri: Redirect URI used in auth request
        nonce: Nonce value for ID token validation
    """
    await _cleanup_expired_states(db)

    oidc_state = OIDCState(
        state=state,
        nonce=nonce,
        redirect_uri=redirect_uri,
        created_at=datetime.now(timezone.utc),
        expires_at=OIDCState.get_expiry_time(minutes=10)
    )
    db.add(oidc_state)
    await db.commit()
    logger.debug("Stored OIDC state: %s...", state[:16])


async def validate_and_consume_state(db: AsyncSession, state: str) -> Optional[Dict[str, Any]]:
    """Validate and consume OIDC state from database (one-time use).

    Args:
        db: Database session
        state: State parameter from callback

    Returns:
        State data if valid, None otherwise
    """
    await _cleanup_expired_states(db)

    # Find and validate state
    result = await db.execute(
        select(OIDCState).where(OIDCState.state == state)
    )
    oidc_state = result.scalar_one_or_none()

    if not oidc_state:
        logger.warning("Invalid or expired OIDC state: %s...", state[:16])
        return None

    if oidc_state.is_expired():
        logger.warning("OIDC state expired: %s...", state[:16])
        await db.delete(oidc_state)
        await db.commit()
        return None

    # Convert to dictionary for compatibility
    state_data = {
        "redirect_uri": oidc_state.redirect_uri,
        "nonce": oidc_state.nonce,
        "created_at": oidc_state.created_at,
    }

    # Delete state (one-time use)
    await db.delete(oidc_state)
    await db.commit()

    logger.debug("Validated and consumed OIDC state: %s...", state[:16])
    return state_data


# ============================================================================
# Authorization Flow
# ============================================================================


async def create_authorization_url(
    db: AsyncSession,
    config: Dict[str, str],
    metadata: Dict[str, Any],
    base_url: str,
) -> tuple[str, str]:
    """Create OIDC authorization URL.

    Args:
        db: Database session
        config: OIDC configuration from database
        metadata: Provider metadata
        base_url: Application base URL (e.g., https://tidewatch.example.com)

    Returns:
        Tuple of (authorization_url, state)
    """
    # Generate state and nonce
    state = generate_state()
    nonce = secrets.token_urlsafe(32)

    # Determine redirect URI
    redirect_uri = config.get("redirect_uri", "").strip()
    if not redirect_uri:
        # Auto-generate redirect URI
        redirect_uri = f"{base_url.rstrip('/')}/api/v1/auth/oidc/callback"

    # Store state for validation in database
    await store_oidc_state(db, state, redirect_uri, nonce)

    # Build authorization URL
    auth_endpoint = metadata.get("authorization_endpoint")
    if not auth_endpoint:
        raise ValueError("Provider metadata missing authorization_endpoint")

    scopes = config.get("scopes", "openid profile email")

    # Build query parameters
    params = {
        "client_id": config.get("client_id", ""),
        "response_type": "code",
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
    }

    # Construct URL
    from urllib.parse import urlencode
    auth_url = f"{auth_endpoint}?{urlencode(params)}"

    logger.info("Created OIDC authorization URL for state: %s", state)
    return auth_url, state


async def exchange_code_for_tokens(
    code: str,
    config: Dict[str, str],
    metadata: Dict[str, Any],
    redirect_uri: str,
) -> Optional[Dict[str, Any]]:
    """Exchange authorization code for tokens.

    Args:
        code: Authorization code from callback
        config: OIDC configuration
        metadata: Provider metadata
        redirect_uri: Redirect URI used in auth request (must match)

    Returns:
        Token response dictionary or None if exchange fails
    """
    token_endpoint = metadata.get("token_endpoint")
    if not token_endpoint:
        logger.error("Provider metadata missing token_endpoint")
        return None

    # SECURITY: Validate token endpoint URL against SSRF attacks
    try:
        validate_oidc_url(token_endpoint)
    except (SSRFProtectionError, ValueError) as e:
        logger.error("SSRF protection blocked token endpoint: %s - %s", token_endpoint, str(e))
        return None

    # Prepare token request
    client_secret = config.get("client_secret", "")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.get("client_id", ""),
        "client_secret": client_secret,
    }

    try:
        async with httpx.AsyncClient() as client:
            logger.info("Exchanging code for tokens at %s", token_endpoint)
            logger.debug("Using redirect_uri: %s", redirect_uri)
            logger.debug("Using client_secret: %s", mask_secret(client_secret))

            response = await client.post(
                token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )

            # Log response details for debugging
            if response.status_code != 200:
                logger.error("Token exchange failed with status %s", response.status_code)
                logger.error("Response body: %s", response.text)

            response.raise_for_status()
            tokens = response.json()

            logger.info("Successfully exchanged authorization code for tokens")
            return tokens

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error during token exchange: %s", e.response.status_code)
        logger.error("Response body: %s", e.response.text)
        return None
    except httpx.TimeoutException:
        logger.error("Token exchange request timed out")
        return None
    except httpx.ConnectError as e:
        logger.error("Cannot connect to OIDC provider for token exchange: %s", str(e))
        return None


async def get_userinfo(
    access_token: str,
    metadata: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Fetch user info from OIDC provider's userinfo endpoint.

    Args:
        access_token: OAuth2 access token
        metadata: Provider metadata containing userinfo_endpoint

    Returns:
        Userinfo claims or None if fetch fails
    """
    userinfo_endpoint = metadata.get("userinfo_endpoint")
    if not userinfo_endpoint:
        logger.warning("Provider metadata missing userinfo_endpoint")
        return None

    # SECURITY: Validate userinfo endpoint URL against SSRF attacks
    try:
        validate_oidc_url(userinfo_endpoint)
    except (SSRFProtectionError, ValueError) as e:
        logger.error("SSRF protection blocked userinfo endpoint: %s - %s", userinfo_endpoint, str(e))
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            response.raise_for_status()
            userinfo = response.json()

            logger.info("Successfully fetched userinfo")
            return userinfo

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error fetching userinfo: %s", e.response.status_code)
        return None
    except httpx.TimeoutException:
        logger.error("Userinfo request timed out")
        return None
    except httpx.ConnectError as e:
        logger.error("Cannot connect to OIDC provider for userinfo: %s", str(e))
        return None


async def verify_id_token(
    id_token: str,
    config: Dict[str, str],
    metadata: Dict[str, Any],
    nonce: str,
) -> Optional[Dict[str, Any]]:
    """Verify and decode ID token from OIDC provider.

    Args:
        id_token: JWT ID token from provider
        config: OIDC configuration
        metadata: Provider metadata
        nonce: Expected nonce value

    Returns:
        Decoded ID token claims or None if validation fails
    """
    try:
        # Get JWKS URI
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            logger.error("Provider metadata missing jwks_uri")
            return None

        # SECURITY: Validate JWKS URI against SSRF attacks
        try:
            validate_oidc_url(jwks_uri)
        except (SSRFProtectionError, ValueError) as e:
            logger.error("SSRF protection blocked JWKS URI: %s - %s", jwks_uri, str(e))
            return None

        # Fetch JWKS
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_uri, timeout=10.0)
            response.raise_for_status()
            jwks = response.json()

        # Create key set
        key_set = JsonWebKey.import_key_set(jwks)

        # Decode and verify ID token
        # Use issuer from metadata as fallback if not configured
        issuer = config.get("issuer_url") or metadata.get("issuer", "")
        claims = jwt.decode(
            id_token,
            key_set,
            claims_options={
                "iss": {"essential": True, "value": issuer},
                "aud": {"essential": True, "value": config.get("client_id", "")},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate()

        logger.info("Successfully verified ID token for subject: %s", claims.get('sub'))
        return dict(claims)

    except JoseError as e:
        logger.error("ID token verification failed: %s", str(e))
        return None
    except httpx.TimeoutException:
        logger.error("JWKS fetch timed out during ID token verification")
        return None
    except httpx.ConnectError as e:
        logger.error("Cannot fetch JWKS for ID token verification: %s", str(e))
        return None


# ============================================================================
# Account Linking (Single User)
# ============================================================================


async def link_oidc_to_admin(
    db: AsyncSession,
    claims: Dict[str, Any],
    userinfo: Optional[Dict[str, Any]],
    config: Dict[str, str],
) -> None:
    """Link OIDC identity to admin account (TideWatch single-user mode).

    Args:
        db: Database session
        claims: ID token claims
        userinfo: Optional userinfo claims from userinfo endpoint
        config: OIDC configuration
    """
    from app.services.auth import update_admin_oidc_link, update_admin_last_login

    sub = claims.get("sub")
    provider_name = config.get("provider_name", "OIDC Provider")

    # Link OIDC to admin
    await update_admin_oidc_link(db, sub, provider_name)

    # Update last login
    await update_admin_last_login(db)

    logger.info("Linked OIDC account to admin user (sub: %s, provider: %s)", sub, provider_name)


async def create_pending_link(
    db: AsyncSession,
    username: str,
    claims: Dict[str, Any],
    userinfo: Optional[Dict[str, Any]],
    config: Dict[str, str],
) -> str:
    """Create pending link token for password verification.

    Args:
        db: Database session
        username: Admin username
        claims: ID token claims
        userinfo: Optional userinfo claims
        config: OIDC configuration

    Returns:
        Pending link token
    """
    await _cleanup_expired_pending_links(db)

    # Generate token
    token = secrets.token_urlsafe(32)

    # Get expiry from config
    expire_minutes = int(config.get("link_token_expire_minutes", "5"))
    provider_name = config.get("provider_name", "OIDC Provider")

    # Create pending link
    pending_link = OIDCPendingLink(
        token=token,
        username=username,
        oidc_claims=json.dumps(claims),
        userinfo_claims=json.dumps(userinfo) if userinfo else None,
        provider_name=provider_name,
        attempt_count=0,
        created_at=datetime.now(timezone.utc),
        expires_at=OIDCPendingLink.get_expiry_time(minutes=expire_minutes)
    )

    db.add(pending_link)
    await db.commit()

    logger.info("Created pending link token for username: %s", username)
    return token


async def verify_pending_link(
    db: AsyncSession,
    token: str,
    password: str,
) -> Optional[Dict[str, Any]]:
    """Verify password and complete OIDC account linking.

    Args:
        db: Database session
        token: Pending link token
        password: Admin password to verify

    Returns:
        ID token claims if successful, None otherwise
    """
    from app.services.auth import get_admin_profile, verify_password

    await _cleanup_expired_pending_links(db)

    # Find pending link
    result = await db.execute(
        select(OIDCPendingLink).where(OIDCPendingLink.token == token)
    )
    pending_link = result.scalar_one_or_none()

    if not pending_link:
        logger.warning("Invalid or expired pending link token")
        return None

    if pending_link.is_expired():
        logger.warning("Pending link token expired")
        await db.delete(pending_link)
        await db.commit()
        return None

    # Check max attempts
    max_attempts = await SettingsService.get(db, "oidc_link_max_password_attempts", default="3")
    if pending_link.attempt_count >= int(max_attempts):
        logger.warning("Max password attempts exceeded for pending link")
        await db.delete(pending_link)
        await db.commit()
        return None

    # Verify password
    profile = await get_admin_profile(db)
    if not profile:
        logger.error("Admin profile not found during pending link verification")
        return None

    password_hash = await SettingsService.get(db, "admin_password_hash", default="")
    if not password_hash:
        logger.error("No password hash found for admin")
        return None

    if not verify_password(password, password_hash):
        # Increment attempt count
        pending_link.attempt_count += 1
        await db.commit()
        logger.warning("Invalid password for pending link (attempt %d)", pending_link.attempt_count)
        return None

    # Password verified - parse claims and delete token
    claims = json.loads(pending_link.oidc_claims)
    await db.delete(pending_link)
    await db.commit()

    logger.info("Pending link verified successfully for username: %s", pending_link.username)
    return claims


# ============================================================================
# Testing
# ============================================================================


async def test_oidc_connection(config: Dict[str, str]) -> Dict[str, Any]:
    """Test OIDC provider connectivity and configuration.

    Args:
        config: OIDC configuration

    Returns:
        Test result dictionary with success status and details
    """
    result = {
        "success": False,
        "provider_reachable": False,
        "metadata_valid": False,
        "endpoints_found": False,
        "errors": [],
        "metadata": None,
    }

    issuer_url = config.get("issuer_url", "").strip()
    if not issuer_url:
        result["errors"].append("Issuer URL is empty")
        return result

    try:
        # Fetch metadata
        metadata = await get_provider_metadata(issuer_url)
        if not metadata:
            result["errors"].append("Failed to fetch provider metadata")
            return result

        result["provider_reachable"] = True
        result["metadata"] = metadata
        result["metadata_valid"] = True

        # Check required endpoints
        required = ["authorization_endpoint", "token_endpoint", "jwks_uri"]
        missing = [ep for ep in required if not metadata.get(ep)]
        if missing:
            result["errors"].append(f"Missing endpoints: {', '.join(missing)}")
            return result

        result["endpoints_found"] = True
        result["success"] = True

    except SSRFProtectionError as e:
        result["errors"].append(f"SSRF protection blocked URL: {str(e)}")
    except Exception as e:
        result["errors"].append(f"Unexpected error: {str(e)}")

    return result
