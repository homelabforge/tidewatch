"""Authentication and OIDC schemas."""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import re


class SetupRequest(BaseModel):
    """Schema for initial admin account setup."""

    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=100)
    full_name: Optional[str] = Field(None, max_length=255)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username format."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Username can only contain letters, numbers, underscores, and hyphens")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class SetupResponse(BaseModel):
    """Response after successful setup."""

    username: str
    email: str
    full_name: Optional[str]
    message: str = "Admin account created successfully"


class LoginRequest(BaseModel):
    """Login request schema."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=100)


class TokenResponse(BaseModel):
    """Token response schema."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: Optional[str] = None


class UserProfile(BaseModel):
    """Admin user profile schema."""

    username: str
    email: str
    full_name: Optional[str]
    auth_method: str  # "local" or "oidc"
    oidc_provider: Optional[str] = None
    created_at: Optional[str] = None  # ISO timestamp string
    last_login: Optional[str] = None  # ISO timestamp string


class UpdateProfileRequest(BaseModel):
    """Schema for updating admin profile."""

    email: Optional[EmailStr] = Field(None, max_length=255)
    full_name: Optional[str] = Field(None, max_length=255)


class ChangePasswordRequest(BaseModel):
    """Schema for changing password."""

    current_password: str = Field(..., min_length=1, max_length=100)
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class AuthStatusResponse(BaseModel):
    """Authentication status response."""

    setup_complete: bool
    auth_mode: str  # "none", "local", "oidc"
    oidc_enabled: bool


# ============================================================================
# OIDC Schemas
# ============================================================================


class OIDCConfig(BaseModel):
    """OIDC configuration schema."""

    enabled: bool = False
    issuer_url: str = Field("", max_length=512)
    client_id: str = Field("", max_length=255)
    client_secret: str = Field("", max_length=255)  # Will be masked in responses
    provider_name: str = Field("", max_length=100)
    scopes: str = Field("openid profile email", max_length=255)
    redirect_uri: str = Field("", max_length=512)
    username_claim: str = Field("preferred_username", max_length=100)
    email_claim: str = Field("email", max_length=100)
    link_token_expire_minutes: int = Field(5, ge=1, le=60)
    link_max_password_attempts: int = Field(3, ge=1, le=10)


class OIDCConfigUpdate(BaseModel):
    """Schema for updating OIDC configuration."""

    enabled: Optional[bool] = None
    issuer_url: Optional[str] = Field(None, max_length=512)
    client_id: Optional[str] = Field(None, max_length=255)
    client_secret: Optional[str] = Field(None, max_length=255)
    provider_name: Optional[str] = Field(None, max_length=100)
    scopes: Optional[str] = Field(None, max_length=255)
    redirect_uri: Optional[str] = Field(None, max_length=512)
    username_claim: Optional[str] = Field(None, max_length=100)
    email_claim: Optional[str] = Field(None, max_length=100)
    link_token_expire_minutes: Optional[int] = Field(None, ge=1, le=60)
    link_max_password_attempts: Optional[int] = Field(None, ge=1, le=10)


class OIDCLinkRequest(BaseModel):
    """Request to link OIDC account with password verification."""

    token: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=100)


class OIDCTestResult(BaseModel):
    """Result of OIDC connection test."""

    success: bool
    provider_reachable: bool = False
    metadata_valid: bool = False
    endpoints_found: bool = False
    errors: list[str] = Field(default_factory=list)
    metadata: Optional[dict] = None


class OIDCProviderMetadata(BaseModel):
    """OIDC provider metadata from discovery."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: Optional[str] = None
    jwks_uri: str
    scopes_supported: Optional[list[str]] = None
    response_types_supported: Optional[list[str]] = None
    subject_types_supported: Optional[list[str]] = None
    id_token_signing_alg_values_supported: Optional[list[str]] = None


class OIDCPendingLinkResponse(BaseModel):
    """Response when OIDC account linking requires password verification."""

    link_required: bool = True
    token: str
    username: str
    provider_name: str
    expires_in_seconds: int
    message: str = "Password verification required to link OIDC account"
