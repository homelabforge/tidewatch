"""CSRF protection middleware for API endpoints."""

import logging
import secrets
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF protection using session-based token storage.

    Improvements over cookie-only implementation:
    - CSRF token stored in server-side session (not just cookie)
    - HttpOnly cookie prevents JavaScript access (XSS protection)
    - Secure cookie in production (HTTPS only)
    - Token rotated per session, not per request
    - Proper constant-time comparison

    Flow:
    - GET/HEAD/OPTIONS: Generate CSRF token, store in session, set HttpOnly cookie
    - POST/PUT/DELETE/PATCH: Validate token from header matches session token
    """

    def __init__(self, app):
        """Initialize CSRF protection middleware.

        Args:
            app: FastAPI application
        """
        super().__init__(app)
        self.exempt_paths = [
            "/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/auth/login",  # Login needs to work without CSRF
            "/api/v1/auth/setup",  # Setup needs to work without CSRF
            "/api/v1/auth/cancel-setup",  # Cancel setup needs to work without CSRF
            "/api/v1/auth/oidc/callback",  # OAuth2 callback can't have CSRF token
            "/api/v1/auth/oidc/test",  # OIDC test endpoint for config validation
        ]

    async def dispatch(self, request: Request, call_next):
        """Process request with CSRF protection.

        Args:
            request: Incoming request
            call_next: Next middleware/endpoint

        Returns:
            Response or CSRF error
        """
        # Disable CSRF protection in test mode
        if os.getenv("TIDEWATCH_TESTING", "false").lower() == "true":
            return await call_next(request)

        # Exempt paths from CSRF protection
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)

        # Safe methods - set CSRF token but don't validate
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            response = await call_next(request)

            # Generate or reuse CSRF token from session
            session = request.session
            csrf_token = session.get("csrf_token")

            if not csrf_token:
                # Generate new token for this session
                csrf_token = secrets.token_urlsafe(32)
                session["csrf_token"] = csrf_token

            # Send CSRF token in response header for frontend to capture
            # Frontend will store this in memory and include it in subsequent requests
            response.headers["X-CSRF-Token"] = csrf_token

            # Also set a cookie for additional validation (not strictly necessary)
            # This cookie is HttpOnly for security - frontend cannot read it
            response.set_cookie(
                key="csrf_token",
                value=csrf_token,
                httponly=True,  # Protects against XSS
                secure=os.getenv("CSRF_SECURE_COOKIE", "false").lower() == "true",
                samesite="lax",
                max_age=86400,  # 24 hours
            )

            return response

        # Unsafe methods (POST, PUT, DELETE, PATCH) - validate CSRF token
        session = request.session
        session_token = session.get("csrf_token")
        header_token = request.headers.get("X-CSRF-Token")

        # Both must be present
        if not session_token or not header_token:
            logger.warning(
                f"CSRF validation failed: missing token "
                f"(session={bool(session_token)}, header={bool(header_token)}) "
                f"for {request.method} {request.url.path}"
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing"}
            )

        # Tokens must match using constant-time comparison
        if not secrets.compare_digest(session_token, header_token):
            logger.warning(f"CSRF validation failed: token mismatch for {request.method} {request.url.path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token invalid"}
            )

        # Token valid, proceed with request
        response = await call_next(request)
        return response
