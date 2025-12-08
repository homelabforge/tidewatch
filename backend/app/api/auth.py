"""Authentication API endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.auth import (
    SetupRequest,
    SetupResponse,
    LoginRequest,
    TokenResponse,
    UserProfile,
    UpdateProfileRequest,
    ChangePasswordRequest,
    AuthStatusResponse,
)
from app.services.auth import (
    is_setup_complete,
    get_admin_profile,
    authenticate_admin,
    create_access_token,
    hash_password,
    verify_password,
    update_admin_profile,
    update_admin_password,
    get_auth_mode,
    require_auth,
    JWT_COOKIE_NAME,
    JWT_COOKIE_MAX_AGE,
)
from app.services.settings_service import SettingsService
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ============================================================================
# Public Endpoints (No Auth Required)
# ============================================================================


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status(
    db: AsyncSession = Depends(get_db),
):
    """Get authentication status (public endpoint).

    Returns setup completion status, auth mode, and OIDC enablement.
    """
    setup_complete = await is_setup_complete(db)
    auth_mode = await get_auth_mode(db)
    oidc_enabled_str = await SettingsService.get(db, "oidc_enabled", default="false")
    oidc_enabled = oidc_enabled_str.lower() == "true"

    return {
        "setup_complete": setup_complete,
        "auth_mode": auth_mode,
        "oidc_enabled": oidc_enabled,
    }


@router.post("/setup", response_model=SetupResponse, status_code=status.HTTP_201_CREATED)
async def setup_admin_account(
    request: Request,
    setup_data: SetupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create initial admin account (first-time setup).

    Only works if no admin account exists yet.
    Automatically enables auth_mode='local' after setup.
    """
    # Check if setup already complete
    if await is_setup_complete(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already complete. Admin account exists.",
        )

    # Hash password
    password_hash = hash_password(setup_data.password)

    # Create admin account in settings
    now = datetime.now(timezone.utc).isoformat()
    await SettingsService.set(db, "admin_username", setup_data.username)
    await SettingsService.set(db, "admin_email", setup_data.email)
    await SettingsService.set(db, "admin_password_hash", password_hash)
    await SettingsService.set(db, "admin_full_name", setup_data.full_name or "")
    await SettingsService.set(db, "admin_auth_method", "local")
    await SettingsService.set(db, "admin_created_at", now)
    await SettingsService.set(db, "admin_last_login", now)

    # Enable local authentication
    await SettingsService.set(db, "auth_mode", "local")

    logger.info("Admin account created: %s", sanitize_log_message(setup_data.username))
    logger.info("Authentication mode set to: local")

    return {
        "username": setup_data.username,
        "email": setup_data.email,
        "full_name": setup_data.full_name or "",
        "message": "Admin account created successfully",
    }


@router.post("/cancel-setup")
async def cancel_setup(db: AsyncSession = Depends(get_db)):
    """Cancel setup and disable authentication (public endpoint).

    This endpoint allows users to cancel the setup process from the setup page
    without requiring authentication. It sets auth_mode back to 'none'.
    """
    # Set auth_mode to none
    await SettingsService.set(db, "auth_mode", "none")

    logger.info("Setup cancelled - authentication disabled")

    return {"message": "Setup cancelled, authentication disabled"}


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate admin user and set JWT token in httpOnly cookie."""
    # Check if setup complete
    if not await is_setup_complete(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup not complete. Please create admin account first.",
        )

    # Authenticate
    profile = await authenticate_admin(db, login_data.username, login_data.password)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create JWT token
    access_token_expires = timedelta(minutes=24 * 60)  # 24 hours
    access_token = create_access_token(
        data={"sub": "admin", "username": profile["username"]},
        expires_delta=access_token_expires
    )

    # Set httpOnly cookie
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=False,  # Set to True if using HTTPS
        samesite="lax",
        max_age=JWT_COOKIE_MAX_AGE,
    )

    logger.info("Admin user logged in: %s", profile["username"])

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": JWT_COOKIE_MAX_AGE,
    }


# ============================================================================
# Protected Endpoints (Auth Required)
# ============================================================================


@router.post("/logout")
async def logout(
    response: Response,
    admin: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Logout admin user by clearing JWT cookie."""
    if not admin:
        # auth_mode is "none", no cookie to clear
        return {"message": "Authentication is disabled"}

    # Clear JWT cookie
    response.delete_cookie(key=JWT_COOKIE_NAME)

    logger.info("Admin user logged out")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserProfile)
async def get_current_admin_profile(
    admin: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get current admin user profile."""
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return {
        "username": admin["username"],
        "email": admin["email"],
        "full_name": admin["full_name"],
        "auth_method": admin["auth_method"],
        "oidc_provider": admin["oidc_provider"] or None,
        "created_at": admin["created_at"] or None,
        "last_login": admin["last_login"] or None,
    }


@router.put("/me", response_model=UserProfile)
async def update_admin_profile_endpoint(
    profile_data: UpdateProfileRequest,
    admin: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update admin profile (email and full name only)."""
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Update profile
    await update_admin_profile(
        db,
        email=profile_data.email,
        full_name=profile_data.full_name,
    )

    # Get updated profile
    updated_profile = await get_admin_profile(db)

    logger.info("Admin profile updated")

    return {
        "username": updated_profile["username"],
        "email": updated_profile["email"],
        "full_name": updated_profile["full_name"],
        "auth_method": updated_profile["auth_method"],
        "oidc_provider": updated_profile["oidc_provider"] or None,
        "created_at": updated_profile["created_at"] or None,
        "last_login": updated_profile["last_login"] or None,
    }


@router.put("/password")
async def change_password(
    password_data: ChangePasswordRequest,
    admin: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Change admin password (local auth only)."""
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Check if admin uses local authentication
    if admin["auth_method"] != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password change not allowed for {admin['auth_method']} authentication. "
                   "Please use your identity provider to change your password.",
        )

    # Verify current password
    current_hash = await SettingsService.get(db, "admin_password_hash", default="")
    if not current_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password hash not found",
        )

    if not verify_password(password_data.current_password, current_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    # Hash new password
    new_hash = hash_password(password_data.new_password)

    # Update password
    await update_admin_password(db, new_hash)

    logger.info("Admin password changed")

    return {"message": "Password changed successfully"}
