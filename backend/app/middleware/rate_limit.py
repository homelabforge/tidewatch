"""Rate limiting middleware for API endpoints."""

import time
import logging
from typing import Dict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

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
        self.tokens = min(
            self.capacity,
            self.tokens + (elapsed * self.refill_rate)
        )
        self.last_refill = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using token bucket algorithm."""

    def __init__(self, app, requests_per_minute: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            app: FastAPI application
            requests_per_minute: Maximum requests per minute per IP
        """
        super().__init__(app)
        self.buckets: Dict[str, TokenBucket] = {}
        self.capacity = requests_per_minute
        self.refill_rate = requests_per_minute / 60.0  # tokens per second
        self.cleanup_interval = 300  # Clean up old buckets every 5 minutes
        self.last_cleanup = time.time()

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request.

        Args:
            request: FastAPI request

        Returns:
            Client IP address
        """
        # Check X-Forwarded-For header (for reverse proxy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def _cleanup_old_buckets(self) -> None:
        """Remove inactive buckets to prevent memory leak.

        Improvements:
        - Reduced cleanup threshold from 10 to 5 minutes
        - Added max bucket limit to prevent unbounded growth
        - Improved logging
        """
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return

        # Remove buckets that haven't been used in 5 minutes (reduced from 10)
        expired_keys = [
            key for key, bucket in self.buckets.items()
            if now - bucket.last_refill > 300  # 5 minutes
        ]

        for key in expired_keys:
            del self.buckets[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} inactive rate limit buckets")

        # Safety check: if we have too many buckets, aggressively clean up oldest
        max_buckets = 10000
        if len(self.buckets) > max_buckets:
            # Sort by last_refill time and keep only the newest max_buckets
            sorted_buckets = sorted(
                self.buckets.items(),
                key=lambda x: x[1].last_refill,
                reverse=True
            )
            self.buckets = dict(sorted_buckets[:max_buckets])
            logger.warning(
                f"Rate limiter exceeded max buckets ({max_buckets}), "
                f"aggressively cleaned up to prevent memory exhaustion"
            )

        self.last_cleanup = now

    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting.

        Args:
            request: Incoming request
            call_next: Next middleware/endpoint

        Returns:
            Response or rate limit error
        """
        # Skip rate limiting for certain paths
        exempt_paths = ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"]
        if any(request.url.path.startswith(path) for path in exempt_paths):
            return await call_next(request)

        # Get client IP
        client_ip = self._get_client_ip(request)

        # Endpoint-specific rate limits (stricter for critical operations)
        endpoint_limits = {
            "/api/v1/containers/": (5, 60),  # 5 requests per minute for container operations
            "/api/v1/updates/": (3, 60),  # 3 requests per minute for update operations
            "/api/v1/settings": (10, 60),  # 10 requests per minute for settings
            "/api/v1/auth/login": (5, 300),  # 5 login attempts per 5 minutes
        }

        # Find matching endpoint limit
        capacity = self.capacity
        refill_rate = self.refill_rate
        bucket_key = client_ip

        for endpoint, (limit, window) in endpoint_limits.items():
            if request.url.path.startswith(endpoint):
                capacity = limit
                refill_rate = limit / (window / 60)  # Convert to per-minute rate
                bucket_key = f"{client_ip}:{endpoint}"
                break

        # Get or create token bucket for this IP/endpoint combo
        if bucket_key not in self.buckets:
            self.buckets[bucket_key] = TokenBucket(capacity, refill_rate)

        bucket = self.buckets[bucket_key]

        # Try to consume a token
        if not bucket.consume():
            logger.warning(f"Rate limit exceeded for IP: {client_ip} on endpoint: {request.url.path}")

            # Calculate retry-after based on endpoint
            retry_after = 60
            for endpoint, (limit, window) in endpoint_limits.items():
                if request.url.path.startswith(endpoint):
                    retry_after = window
                    break

            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(retry_after)}
            )

        # Periodic cleanup
        self._cleanup_old_buckets()

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.capacity)
        response.headers["X-RateLimit-Remaining"] = str(int(bucket.tokens))

        return response
