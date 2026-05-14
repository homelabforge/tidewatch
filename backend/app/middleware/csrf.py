"""CSRF protection middleware for API endpoints.

Pure ASGI middleware rather than Starlette's `BaseHTTPMiddleware`: the latter
buffers the response body through an internal asyncio queue, which is fine
for small JSON but throttles streaming responses (e.g. SSE event streams,
photo serving, large file downloads). Pure ASGI wraps `send` directly and
only touches the `http.response.start` message — the body streams through.
"""

import json
import logging
import os
import secrets

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class CSRFProtectionMiddleware:
    """CSRF protection using session-based token storage.

    Improvements over cookie-only implementation:
    - CSRF token stored in server-side session (not just cookie)
    - HttpOnly cookie prevents JavaScript access (XSS protection)
    - Secure cookie in production (HTTPS only)
    - Token rotated per session, not per request
    - Proper constant-time comparison

    Flow:
    - GET/HEAD/OPTIONS: Generate CSRF token, store in session, set HttpOnly
      cookie, echo token in `X-CSRF-Token` response header.
    - POST/PUT/DELETE/PATCH: Validate header token against session token.

    Requires Starlette's `SessionMiddleware` to run *outside* of this one so
    that `scope["session"]` is populated.
    """

    DEFAULT_EXEMPT_PATHS: tuple[str, ...] = (
        "/health",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/login",
        "/api/v1/auth/setup",
        "/api/v1/auth/cancel-setup",
        "/api/v1/auth/oidc/callback",
        "/api/v1/auth/oidc/test",
        # Static asset paths. These are idempotent GETs that do not need a
        # CSRF token, and emitting one on every request attaches a
        # `Set-Cookie` header that makes Cloudflare refuse to cache the
        # asset (`cf-cache-status: BYPASS`). The CSRF cookie is set on the
        # HTML and API responses where it is actually used.
        "/assets/",
        "/vite.svg",
        "/favicon.ico",
    )

    def __init__(self, app: ASGIApp, force_enabled: bool = False) -> None:
        self.app = app
        self.force_enabled = force_enabled
        self.exempt_paths = self.DEFAULT_EXEMPT_PATHS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Test-mode bypass.
        if not self.force_enabled and os.getenv("TIDEWATCH_TESTING", "false").lower() == "true":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in self.exempt_paths):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")

        if method in ("GET", "HEAD", "OPTIONS"):
            await self._handle_safe_method(scope, receive, send)
            return

        await self._handle_unsafe_method(scope, receive, send)

    async def _handle_safe_method(self, scope: Scope, receive: Receive, send: Send) -> None:
        """For safe methods: generate/reuse CSRF token, decorate the response."""
        session = scope.get("session")
        if session is None:
            # No SessionMiddleware in the chain — nothing we can do. Pass through.
            await self.app(scope, receive, send)
            return

        csrf_token = session.get("csrf_token")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf_token

        secure_cookie = os.getenv("CSRF_SECURE_COOKIE", "false").lower() == "true"
        cookie_parts = [
            f"csrf_token={csrf_token}",
            "HttpOnly",
            "Max-Age=86400",
            "SameSite=lax",
            "Path=/",
        ]
        if secure_cookie:
            cookie_parts.append("Secure")
        cookie_value = "; ".join(cookie_parts)

        async def send_with_csrf(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-CSRF-Token"] = csrf_token
                headers.append("Set-Cookie", cookie_value)
            await send(message)

        await self.app(scope, receive, send_with_csrf)

    async def _handle_unsafe_method(self, scope: Scope, receive: Receive, send: Send) -> None:
        """For unsafe methods: validate header CSRF token against session token."""
        session = scope.get("session") or {}
        session_token = session.get("csrf_token")
        header_token = _get_header(scope, b"x-csrf-token")

        if not session_token or not header_token:
            logger.warning(
                "CSRF validation failed: missing token (session=%s, header=%s) for %s %s",
                bool(session_token),
                bool(header_token),
                scope.get("method", "?"),
                scope.get("path", "?"),
            )
            await _send_json(send, status=403, payload={"detail": "CSRF token missing"})
            return

        if not secrets.compare_digest(session_token, header_token):
            logger.warning(
                "CSRF validation failed: token mismatch for %s %s",
                scope.get("method", "?"),
                scope.get("path", "?"),
            )
            await _send_json(send, status=403, payload={"detail": "CSRF token invalid"})
            return

        await self.app(scope, receive, send)


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Look up a request header value (case-insensitive) from the ASGI scope."""
    name_lower = name.lower()
    for key, value in scope.get("headers", []):
        if key.lower() == name_lower:
            return value.decode("latin-1")
    return None


async def _send_json(send: Send, *, status: int, payload: dict) -> None:
    """Emit a JSON response from inside ASGI middleware."""
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
