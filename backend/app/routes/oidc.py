"""OIDC authentication routes for TideWatch.

Provides endpoints for OIDC/OpenID Connect authentication flow:
- GET /api/v1/auth/oidc/config - Get OIDC configuration (admin only, client_secret masked)
- PUT /api/v1/auth/oidc/config - Update OIDC configuration (admin only)
- POST /api/v1/auth/oidc/test - Test OIDC provider connection (admin only)
- GET /api/v1/auth/oidc/login - Initiate OIDC flow (public, redirects to provider)
- GET /api/v1/auth/oidc/callback - Handle OIDC callback (public)
- POST /api/v1/auth/oidc/link-account - Link OIDC with password verification (public)

Single-User Adaptations:
- All OIDC logins link to the single admin account
- No user creation, only account linking
- Settings-based configuration storage
"""

import logging
import httpx
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from authlib.jose import JoseError

from app.database import get_db
from app.schemas.auth import OIDCConfig, OIDCTestResult
from app.services import oidc as oidc_service
from app.utils.security import sanitize_log_message
from app.services.auth import (
    create_access_token,
    require_auth,
    JWT_COOKIE_NAME,
    JWT_COOKIE_MAX_AGE,
    is_setup_complete,
)
from app.services.settings_service import SettingsService
from app.exceptions import PendingLinkRequiredException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["OIDC Authentication"])


# ============================================================================
# Protected Endpoints (Admin Auth Required)
# ============================================================================


@router.get("/config", response_model=OIDCConfig)
async def get_oidc_config(
    admin: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get OIDC configuration (admin only).

    Returns configuration with client_secret masked for security.
    """
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Get OIDC config from settings
    config = await oidc_service.get_oidc_config(db)

    # Mask client_secret for security
    masked_secret = oidc_service.mask_secret(config.get("client_secret", ""))

    return {
        "enabled": config.get("enabled", "false").lower() == "true",
        "issuer_url": config.get("issuer_url", ""),
        "client_id": config.get("client_id", ""),
        "client_secret": masked_secret,
        "provider_name": config.get("provider_name", ""),
        "scopes": config.get("scopes", "openid profile email"),
        "redirect_uri": config.get("redirect_uri", ""),
    }


@router.put("/config")
async def update_oidc_config(
    oidc_config: OIDCConfig,
    admin: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update OIDC configuration (admin only).

    Args:
        oidc_config: New OIDC configuration

    Returns:
        Success message
    """
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # DEBUG: Log received configuration
    logger.info(
        "Received OIDC config: enabled=%s, issuer_url='%s', client_id='%s', "
        "client_secret='%s', provider_name='%s', scopes='%s', redirect_uri='%s'",
        oidc_config.enabled,
        sanitize_log_message(oidc_config.issuer_url),
        sanitize_log_message(oidc_config.client_id),
        "***MASKED***" if oidc_config.client_secret else "<<EMPTY>>",
        sanitize_log_message(oidc_config.provider_name),
        sanitize_log_message(str(oidc_config.scopes)),
        sanitize_log_message(oidc_config.redirect_uri),
    )

    # If client_secret is masked, keep the existing secret instead of overwriting
    client_secret = oidc_config.client_secret
    if oidc_service.is_masked_secret(client_secret):
        existing_secret = await SettingsService.get(
            db, "oidc_client_secret", default=""
        )
        client_secret = existing_secret

    # Update OIDC settings
    await SettingsService.set(db, "oidc_enabled", str(oidc_config.enabled).lower())
    await SettingsService.set(db, "oidc_issuer_url", oidc_config.issuer_url)
    await SettingsService.set(db, "oidc_client_id", oidc_config.client_id)
    await SettingsService.set(db, "oidc_client_secret", client_secret)
    await SettingsService.set(db, "oidc_provider_name", oidc_config.provider_name)
    await SettingsService.set(db, "oidc_scopes", oidc_config.scopes)
    await SettingsService.set(db, "oidc_redirect_uri", oidc_config.redirect_uri or "")

    logger.info(
        "OIDC configuration updated by admin: %s",
        sanitize_log_message(admin["username"]),
    )

    return {"message": "OIDC configuration updated successfully"}


@router.post("/test", response_model=OIDCTestResult)
async def test_oidc_connection(
    oidc_config: OIDCConfig,
    admin: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Test OIDC provider connection (admin only).

    Tests connectivity and metadata retrieval without performing full auth flow.

    Args:
        oidc_config: OIDC configuration to test

    Returns:
        Test results with success/failure and any errors
    """
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # If client_secret is masked, use existing secret
    client_secret = oidc_config.client_secret
    if oidc_service.is_masked_secret(client_secret):
        existing_secret = await SettingsService.get(
            db, "oidc_client_secret", default=""
        )
        client_secret = existing_secret

    # Convert to config dict
    config = {
        "issuer_url": sanitize_log_message(oidc_config.issuer_url),
        "client_id": sanitize_log_message(oidc_config.client_id),
        "client_secret": client_secret,
    }

    # Test connection
    result = await oidc_service.test_oidc_connection(config)

    logger.info(
        "OIDC connection test by admin %s: %s",
        sanitize_log_message(admin["username"]),
        "success" if result["success"] else "failed",
    )

    return result


# ============================================================================
# Public Endpoints (No Auth Required)
# ============================================================================


@router.get("/login")
async def oidc_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Initiate OIDC authentication flow (public).

    Redirects user to OIDC provider for authentication.

    Returns:
        Redirect to OIDC provider authorization endpoint
    """
    # Check if setup is complete
    if not await is_setup_complete(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup not complete. Please create admin account first.",
        )

    # Get OIDC configuration
    config = await oidc_service.get_oidc_config(db)

    # Check if OIDC is enabled
    if config.get("enabled", "false").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC authentication is not enabled",
        )

    # Validate configuration
    issuer_url = config.get("issuer_url", "").strip()
    client_id = config.get("client_id", "").strip()

    if not issuer_url or not client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC is not properly configured (missing issuer_url or client_id)",
        )

    # Fetch provider metadata
    try:
        metadata = await oidc_service.get_provider_metadata(issuer_url)
        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch OIDC provider metadata",
            )
    except httpx.TimeoutException:
        logger.error("OIDC provider timeout fetching metadata")
        raise HTTPException(status_code=504, detail="OIDC provider request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to OIDC provider")
        raise HTTPException(status_code=503, detail="Cannot connect to OIDC provider")

    # Determine base URL for redirect URI
    base_url = str(request.base_url).rstrip("/")
    # Handle reverse proxy headers (Traefik)
    if request.headers.get("x-forwarded-proto"):
        scheme = request.headers.get("x-forwarded-proto")
        host = request.headers.get("x-forwarded-host", request.headers.get("host"))
        base_url = f"{scheme}://{host}"

    # Create authorization URL
    try:
        auth_url, state = await oidc_service.create_authorization_url(
            db, config, metadata, base_url
        )
    except httpx.TimeoutException:
        logger.error("OIDC provider timeout creating authorization URL")
        raise HTTPException(status_code=504, detail="OIDC provider request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to OIDC provider")
        raise HTTPException(status_code=503, detail="Cannot connect to OIDC provider")
    except JoseError as e:
        logger.error("OIDC JWT error creating authorization URL: %s", e)
        raise HTTPException(status_code=401, detail="OIDC authentication error")
    except (ValueError, KeyError) as e:
        logger.error("OIDC configuration error: %s", e)
        raise HTTPException(status_code=500, detail="OIDC configuration error")

    logger.info(
        "Redirecting to OIDC provider for authentication (state: %s)",
        sanitize_log_message(state[:16]),
    )
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def oidc_callback(
    code: str,
    state: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Handle OIDC callback from provider (public).

    Query Parameters:
        code: Authorization code from provider
        state: State parameter for CSRF protection

    Returns:
        Redirect to frontend with JWT cookie set
    """
    logger.info("Received OIDC callback (state: %s)", sanitize_log_message(state[:16]))

    # Validate and consume state from database (one-time use)
    state_data = await oidc_service.validate_and_consume_state(db, state)
    if not state_data:
        logger.warning(
            "Invalid or expired state parameter: %s", sanitize_log_message(state[:16])
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter. Please try logging in again.",
        )

    # Get OIDC configuration
    config = await oidc_service.get_oidc_config(db)
    issuer_url = config.get("issuer_url", "").strip()

    # Fetch provider metadata
    try:
        metadata = await oidc_service.get_provider_metadata(issuer_url)
        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch OIDC provider metadata",
            )
    except httpx.TimeoutException:
        logger.error("OIDC provider timeout fetching metadata")
        raise HTTPException(status_code=504, detail="OIDC provider request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to OIDC provider")
        raise HTTPException(status_code=503, detail="Cannot connect to OIDC provider")

    # Exchange code for tokens
    redirect_uri = state_data["redirect_uri"]
    try:
        tokens = await oidc_service.exchange_code_for_tokens(
            code, config, metadata, redirect_uri
        )
        if not tokens:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to exchange authorization code for tokens",
            )
    except httpx.TimeoutException:
        logger.error("OIDC provider timeout exchanging code for tokens")
        raise HTTPException(status_code=504, detail="OIDC provider request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to OIDC provider")
        raise HTTPException(status_code=503, detail="Cannot connect to OIDC provider")

    # Verify ID token
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Provider did not return ID token",
        )

    nonce = state_data["nonce"]
    try:
        claims = await oidc_service.verify_id_token(id_token, config, metadata, nonce)
        if not claims:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to verify ID token",
            )
    except JoseError as e:
        logger.error("ID token verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to verify ID token",
        )

    # Fetch userinfo (optional, provides additional claims)
    access_token = tokens.get("access_token")
    userinfo = None
    if access_token:
        try:
            userinfo = await oidc_service.get_userinfo(access_token, metadata)
        except (httpx.TimeoutException, httpx.ConnectError):
            logger.warning(
                "Failed to fetch userinfo, continuing with ID token claims only"
            )

    # Link OIDC to admin account
    try:
        await oidc_service.link_oidc_to_admin(db, claims, userinfo, config)
    except PendingLinkRequiredException as e:
        # Admin account requires password verification before linking
        logger.info("Pending link required for admin account")

        # Create pending link token
        pending_token = await oidc_service.create_pending_link(
            db,
            e.username,
            e.claims,
            e.userinfo,
            e.config,
        )

        # Redirect to link account page with token
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", str(request.base_url.hostname))
        frontend_url = f"{scheme}://{host}"
        redirect_url = f"{frontend_url}/auth/link-account?token={pending_token}"

        logger.info("Redirecting to link account page")
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # Get admin profile
    from app.services.auth import get_admin_profile

    admin_profile = await get_admin_profile(db)
    if not admin_profile:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve admin profile after OIDC link",
        )

    # Create JWT token for admin
    access_token_expires = timedelta(minutes=24 * 60)  # 24 hours
    jwt_token = create_access_token(
        data={"sub": "admin", "username": admin_profile["username"]},
        expires_delta=access_token_expires,
    )

    logger.info("OIDC login successful for admin: %s", admin_profile["username"])

    # Set httpOnly cookie and redirect to frontend
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", str(request.base_url.hostname))
    frontend_url = f"{scheme}://{host}"
    redirect_url = f"{frontend_url}/"

    redirect_response = RedirectResponse(
        url=redirect_url, status_code=status.HTTP_302_FOUND
    )
    redirect_response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        secure=False,  # Set to True if using HTTPS
        samesite="lax",
        max_age=JWT_COOKIE_MAX_AGE,
    )

    return redirect_response


@router.post("/link-account")
async def link_oidc_account(
    request: Request,
    response: Response,
    token: str,
    password: str,
    db: AsyncSession = Depends(get_db),
):
    """Link OIDC account to admin with password verification (public).

    This endpoint is called after OIDC login when the admin account requires
    password verification to link the OIDC identity.

    Security:
    - Max 3 password attempts per token
    - Token expires after 5 minutes
    - One-time use (token deleted after success)

    Args:
        token: Pending link token from callback redirect
        password: Admin password for verification
        request: FastAPI request for header extraction
        response: FastAPI response for cookie setting
        db: Database session

    Returns:
        Redirect to frontend with JWT cookie set

    Raises:
        HTTPException: 401 if token invalid/expired or password incorrect
    """
    # Validate and consume pending link token
    result = await oidc_service.verify_pending_link(db, token, password)

    if not result["success"]:
        logger.warning("OIDC link failed: %s", result["error"])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["error"],
        )

    # Get admin profile
    from app.services.auth import get_admin_profile

    admin_profile = await get_admin_profile(db)
    if not admin_profile:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve admin profile after OIDC link",
        )

    # Create JWT token for admin
    access_token_expires = timedelta(minutes=24 * 60)  # 24 hours
    jwt_token = create_access_token(
        data={"sub": "admin", "username": admin_profile["username"]},
        expires_delta=access_token_expires,
    )

    logger.info(
        "OIDC account linked successfully for admin: %s", admin_profile["username"]
    )

    # Set httpOnly cookie
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        secure=False,  # Set to True if using HTTPS
        samesite="lax",
        max_age=JWT_COOKIE_MAX_AGE,
    )

    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "expires_in": JWT_COOKIE_MAX_AGE,
    }
