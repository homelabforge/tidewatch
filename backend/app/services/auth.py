"""Authentication service for TideWatch - single-user JWT auth with User model."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from authlib.jose import JoseError, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

# HTTP Bearer token
security = HTTPBearer(auto_error=False)

# JWT Configuration
JWT_SECRET_KEY_FILE = Path("/data/secret.key")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60  # 24 hours
JWT_COOKIE_NAME = "tidewatch_token"
JWT_COOKIE_MAX_AGE = 86400  # 24 hours in seconds

# Initialize Argon2 password hasher with recommended parameters
# time_cost=2, memory_cost=102400 (100MB), parallelism=8
ph = PasswordHasher(time_cost=2, memory_cost=102400, parallelism=8)


# ============================================================================
# Secret Key Management
# ============================================================================


def get_or_create_secret_key(key_file: Path = JWT_SECRET_KEY_FILE) -> str:
    """Get existing or create new secret key.

    If the secret key file exists, reads and returns it.
    If not, generates a new cryptographically secure key and saves it.

    Args:
        key_file: Path to the secret key file (default: /data/secret.key)

    Returns:
        The secret key as a string

    Note:
        Falls back to in-memory key generation if file operations fail.
        This means the key will change on restart, logging out all users.
    """
    from app.utils.security import sanitize_path

    try:
        # Validate key file path to prevent path traversal
        # JWT secret key must be in /data directory
        validated_key_file = sanitize_path(str(key_file), "/data", allow_symlinks=False)

        # Check if key file already exists
        if validated_key_file.exists():
            secret_key = validated_key_file.read_text().strip()
            if secret_key:
                logger.debug("Loaded existing secret key from %s", validated_key_file)
                return secret_key
            else:
                logger.warning(
                    "Secret key file at %s is empty, generating new key",
                    validated_key_file,
                )

        # Generate cryptographically secure key (32 bytes = 256 bits)
        secret_key = secrets.token_urlsafe(32)

        # Ensure parent directory exists
        validated_key_file.parent.mkdir(parents=True, exist_ok=True)

        # Write key to file
        # lgtm[py/clear-text-storage-sensitive-data] - JWT secret key must persist across restarts
        # File is stored in protected /data/ directory with 0o600 permissions
        validated_key_file.write_text(secret_key)

        # Set restrictive permissions (owner read/write only)
        validated_key_file.chmod(0o600)

        logger.info("Generated new secret key and saved to %s", validated_key_file)
        logger.info("Secret key will persist across container restarts")

        return secret_key

    except (ValueError, FileNotFoundError) as e:
        logger.error("Invalid secret key file path: %s", str(e))
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32)

    except PermissionError as e:
        logger.error("Permission denied when accessing secret key file: %s", str(e))
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32)

    except Exception as e:
        logger.error("Failed to handle secret key file: %s", str(e), exc_info=True)
        logger.warning("Using temporary in-memory secret key (will change on restart)")
        return secrets.token_urlsafe(32)


# Load secret key on module import
_SECRET_KEY = get_or_create_secret_key()


# ============================================================================
# Password Operations
# ============================================================================


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an Argon2 hash.

    Note: TideWatch is a new app, so we only support Argon2 hashes.
    No bcrypt legacy support needed.
    """
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError, InvalidHashError:
        return False


def hash_password(password: str) -> str:
    """Hash a password using Argon2id.

    Uses Argon2id with recommended parameters:
    - time_cost=2
    - memory_cost=102400 (100MB)
    - parallelism=8

    Note: Argon2 has no password length limitation (unlike bcrypt's 72 bytes).
    """
    return ph.hash(password)


# ============================================================================
# JWT Operations
# ============================================================================


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": datetime.now(UTC)})
    header = {"alg": JWT_ALGORITHM}
    encoded_jwt = jwt.encode(header, to_encode, _SECRET_KEY)
    return encoded_jwt.decode("utf-8") if isinstance(encoded_jwt, bytes) else encoded_jwt


def get_token_from_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """Extract JWT token from cookie or Authorization header.

    Priority:
    1. Cookie (primary method)
    2. Authorization header (backward compatibility)
    """
    # Try cookie first
    token = request.cookies.get(JWT_COOKIE_NAME)
    if token:
        return token

    # Fall back to Authorization header
    if credentials:
        return credentials.credentials

    return None


def decode_token(token: str) -> dict:
    """Decode and validate JWT token.

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, _SECRET_KEY)

        # Manually validate expiration (authlib doesn't do this automatically)
        import time

        if "exp" in payload:
            if payload["exp"] < time.time():
                logger.error("JWT token has expired")
                raise credentials_exception

        return payload
    except JoseError as e:
        logger.error("JWT decode error: %s", e)
        raise credentials_exception


# ============================================================================
# User Model Helpers
# ============================================================================


async def _get_admin_user(db: AsyncSession) -> User | None:
    """Get the admin user from the database.

    Returns:
        User instance or None if no admin account exists.
    """
    result = await db.execute(select(User).limit(1))
    return result.scalar_one_or_none()


# ============================================================================
# Admin Profile Management
# ============================================================================


async def is_setup_complete(db: AsyncSession) -> bool:
    """Check if admin account has been created.

    Returns:
        True if auth_mode is "none" (no setup required) or admin account exists
    """
    # If auth is disabled, setup is considered complete (no account needed)
    auth_mode = await get_auth_mode(db)
    if auth_mode == "none":
        return True

    # For local/OIDC auth, check if admin account exists
    user = await _get_admin_user(db)
    return user is not None


async def get_admin_profile(db: AsyncSession) -> dict | None:
    """Get admin profile from User model.

    Returns:
        Dict with admin profile data, or None if setup not complete
    """
    if not await is_setup_complete(db):
        return None

    user = await _get_admin_user(db)
    if not user:
        return None

    return user.to_profile_dict()


async def update_admin_profile(
    db: AsyncSession, email: str | None = None, full_name: str | None = None
) -> None:
    """Update admin profile."""
    user = await _get_admin_user(db)
    if not user:
        return

    if email is not None:
        user.email = email
    if full_name is not None:
        user.full_name = full_name
    await db.commit()


async def update_admin_password(db: AsyncSession, new_hash: str) -> None:
    """Update admin password hash."""
    user = await _get_admin_user(db)
    if not user:
        return

    user.password_hash = new_hash
    await db.commit()


async def update_admin_oidc_link(db: AsyncSession, oidc_subject: str, provider: str) -> None:
    """Link OIDC identity to admin account."""
    user = await _get_admin_user(db)
    if not user:
        return

    user.oidc_subject = oidc_subject
    user.oidc_provider = provider
    user.auth_method = "oidc"
    await db.commit()


async def update_admin_last_login(db: AsyncSession) -> None:
    """Update admin last login timestamp."""
    user = await _get_admin_user(db)
    if not user:
        return

    user.last_login = datetime.now(UTC)
    await db.commit()


async def create_admin_user(
    db: AsyncSession,
    username: str,
    email: str,
    password_hash: str,
    full_name: str = "",
) -> User:
    """Create the admin user account.

    Args:
        db: Database session
        username: Admin username
        email: Admin email
        password_hash: Argon2 password hash
        full_name: Admin full name

    Returns:
        Created User instance
    """
    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        auth_method="local",
        last_login=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_admin_password_hash(db: AsyncSession) -> str:
    """Get admin password hash for verification.

    Returns:
        Password hash string, or empty string if no admin exists.
    """
    user = await _get_admin_user(db)
    if not user:
        return ""
    return user.password_hash


# ============================================================================
# Authentication
# ============================================================================


async def authenticate_admin(db: AsyncSession, username: str, password: str) -> dict | None:
    """Authenticate admin user by username and password.

    Returns:
        Admin profile dict if authenticated, None otherwise
    """
    user = await _get_admin_user(db)
    if not user:
        return None

    # Check username matches
    if user.username != username:
        return None

    # Check password hash exists
    if not user.password_hash:
        logger.warning("Password login attempted but no password hash set")
        return None

    # Check auth method - reject password login for OIDC-only users
    if user.auth_method == "oidc":
        logger.warning("Password login attempted for OIDC-linked admin account")
        return None

    # Verify password
    if not verify_password(password, user.password_hash):
        return None

    # Update last login
    await update_admin_last_login(db)

    return user.to_profile_dict()


async def get_current_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(get_token_from_request),
) -> dict:
    """Get the current authenticated admin from JWT token.

    Returns:
        Admin profile dict

    Raises:
        HTTPException 401: If token is invalid or missing
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        logger.error("No credentials provided - %s %s", request.method, request.url.path)
        raise credentials_exception

    logger.debug("Processing authentication token")

    # Decode token
    payload = decode_token(token)

    # Validate token structure
    sub = payload.get("sub")
    username = payload.get("username")

    if sub is None or username is None:
        logger.error("Token missing sub or username")
        raise credentials_exception

    # For single-user TideWatch, sub should be "admin"
    if sub != "admin":
        logger.error("Invalid token subject: %s", sub)
        raise credentials_exception

    # Get admin profile from User model
    profile = await get_admin_profile(db)
    if not profile:
        logger.error("Admin profile not found")
        raise credentials_exception

    # Verify username matches
    if profile["username"] != username:
        logger.error("Token username mismatch")
        raise credentials_exception

    logger.debug("Token validated successfully for admin user")
    return profile


async def require_auth(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(get_token_from_request),
) -> dict | None:
    """Require authentication - checks auth_mode setting.

    Returns:
        Admin profile dict if authenticated.
        None if auth_mode='none' (authentication disabled).

    Raises:
        HTTPException 401: If auth is enabled but user is not authenticated.
    """
    auth_mode = await get_auth_mode(db)

    # If auth is disabled, return None
    if auth_mode == "none":
        return None

    # Auth is enabled - enforce authentication
    return await get_current_admin(request, db, token)


async def optional_auth(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(get_token_from_request),
) -> dict | None:
    """Optional authentication based on auth_mode setting.

    Returns:
        Admin profile dict if authenticated.
        None if auth_mode='none' or no credentials provided.
    """
    auth_mode = await get_auth_mode(db)

    if auth_mode == "none":
        return None

    # Auth optional - try to get current user, but don't raise if missing
    if not token:
        return None

    try:
        return await get_current_admin(request, db, token)
    except HTTPException:
        return None


# ============================================================================
# Auth Mode Management
# ============================================================================


async def get_auth_mode(db: AsyncSession) -> str:
    """Get the current authentication mode from settings.

    Returns:
        "none", "local", or "oidc"
    """
    auth_mode = await SettingsService.get(db, "auth_mode", default="none")
    # Handle None case (fallback if SettingsService returns None)
    if auth_mode is None:
        return "none"
    return auth_mode.lower()
