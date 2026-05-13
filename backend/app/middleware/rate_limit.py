"""Rate limiting middleware for API endpoints.

Pure ASGI middleware rather than Starlette's `BaseHTTPMiddleware`: the latter
buffers the entire response body before forwarding, which throttles streaming
responses (SSE event streams, large file responses). Pure ASGI wraps `send`
directly and only inspects the `http.response.start` message to attach the
`X-RateLimit-*` headers.
"""

import json
import logging
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket for rate limiting."""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        """Initialize token bucket.

        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if insufficient
        """
        now = time.time()
        elapsed = now - self.last_refill

        # Refill tokens based on elapsed time
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
        self.last_refill = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


# Endpoint-specific overrides: (capacity, window_seconds).
_ENDPOINT_LIMITS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("/api/v1/containers/", (5, 60)),
    ("/api/v1/updates/", (3, 60)),
    ("/api/v1/settings", (10, 60)),
    ("/api/v1/auth/login", (5, 300)),
)

_EXEMPT_PATHS: tuple[str, ...] = (
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class RateLimitMiddleware:
    """Rate limiting middleware using a token bucket algorithm."""

    def __init__(self, app: ASGIApp, requests_per_minute: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            app: ASGI app
            requests_per_minute: Maximum requests per minute per IP
        """
        self.app = app
        self.buckets: dict[str, TokenBucket] = {}
        self.capacity = requests_per_minute
        self.refill_rate = requests_per_minute / 60.0  # tokens per second
        self.cleanup_interval: float = 300  # Clean up old buckets every 5 minutes
        self.last_cleanup = time.time()

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP from request scope (X-Forwarded-For > X-Real-IP > peer)."""
        forwarded = _get_header(scope, b"x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = _get_header(scope, b"x-real-ip")
        if real_ip:
            return real_ip

        client = scope.get("client")
        if client:
            return client[0]

        return "unknown"

    def _resolve_limits(self, path: str, client_ip: str) -> tuple[int, float, str, int]:
        """Pick the right (capacity, refill_rate, bucket_key, retry_after) for `path`.

        Preserves the original calculation (`limit / (window / 60)`) verbatim
        so this rewrite is purely a streaming fix and does not change observed
        rate-limit behavior. The number lands in `bucket.refill_rate` which is
        applied as tokens-per-second by `TokenBucket.consume()`.
        """
        for endpoint, (limit, window) in _ENDPOINT_LIMITS:
            if path.startswith(endpoint):
                refill_rate = limit / (window / 60)
                return limit, refill_rate, f"{client_ip}:{endpoint}", window
        return self.capacity, self.refill_rate, client_ip, 60

    def _cleanup_old_buckets(self) -> None:
        """Remove inactive buckets to prevent memory leak.

        - Drops buckets idle for more than 5 minutes.
        - If we still exceed `max_buckets`, keep only the newest.
        """
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return

        expired_keys = [
            key for key, bucket in self.buckets.items() if now - bucket.last_refill > 300
        ]
        for key in expired_keys:
            del self.buckets[key]

        if expired_keys:
            logger.debug("Cleaned up %d inactive rate limit buckets", len(expired_keys))

        max_buckets = 10000
        if len(self.buckets) > max_buckets:
            sorted_buckets = sorted(
                self.buckets.items(),
                key=lambda x: x[1].last_refill,
                reverse=True,
            )
            self.buckets = dict(sorted_buckets[:max_buckets])
            logger.warning(
                "Rate limiter exceeded max buckets (%d), aggressively cleaned up to "
                "prevent memory exhaustion",
                max_buckets,
            )

        self.last_cleanup = now

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in _EXEMPT_PATHS):
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(scope)
        capacity, refill_rate, bucket_key, retry_after = self._resolve_limits(path, client_ip)

        bucket = self.buckets.get(bucket_key)
        if bucket is None:
            bucket = TokenBucket(capacity, refill_rate)
            self.buckets[bucket_key] = bucket

        if not bucket.consume():
            logger.warning("Rate limit exceeded for IP: %s on endpoint: %s", client_ip, path)
            await _send_json(
                send,
                status=429,
                payload={"detail": "Rate limit exceeded. Please try again later."},
                extra_headers=[(b"retry-after", str(retry_after).encode("ascii"))],
            )
            return

        self._cleanup_old_buckets()

        # Snapshot capacity/remaining for the response decoration. `consume()`
        # already debited the bucket, so `bucket.tokens` here is the post-debit
        # remaining count.
        remaining = int(bucket.tokens)
        limit = capacity

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-RateLimit-Limit"] = str(limit)
                headers["X-RateLimit-Remaining"] = str(remaining)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Case-insensitive header lookup from the ASGI scope."""
    name_lower = name.lower()
    for key, value in scope.get("headers", []):
        if key.lower() == name_lower:
            return value.decode("latin-1")
    return None


async def _send_json(
    send: Send,
    *,
    status: int,
    payload: dict,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """Emit a JSON response from inside ASGI middleware."""
    body = json.dumps(payload).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
