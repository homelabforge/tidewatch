"""TideWatch - Intelligent Docker Container Update Manager."""

import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.database import AsyncSessionLocal, init_db
from app.services.scheduler import scheduler_service
from app.services.settings_service import SettingsService
from app.utils.version import get_app_version


def _configure_logging() -> None:
    """Configure root logging.

    When TIDEWATCH_LOG_PRETTY is truthy, use Rich with a layout that matches
    the myfinances pino-pretty look: time-only prefix (Docker adds the date
    in its log driver), colored level, no logger-name column, no wrapping.
    Otherwise fall back to the plain machine-friendly format suitable for log
    aggregators.
    """
    level = os.getenv("LOG_LEVEL", "INFO")
    pretty = os.getenv("TIDEWATCH_LOG_PRETTY", "false").lower() in ("true", "1", "yes")

    handlers: list[logging.Handler]
    fmt: str
    if pretty:
        try:
            from rich.console import Console
            from rich.logging import RichHandler

            # Force a wide console so long log lines don't wrap to multiple
            # rows. Docker's log capture reports the terminal width as 80
            # which makes Rich fold messages aggressively.
            console = Console(
                width=240,
                force_terminal=True,
                no_color=False,
                highlight=False,
            )
            handlers = [
                RichHandler(
                    console=console,
                    rich_tracebacks=True,
                    show_path=False,
                    omit_repeated_times=False,
                    markup=False,
                    log_time_format="[%X]",
                )
            ]
            # Rich already shows time + level columns; we deliberately drop
            # the logger name so the output mirrors myfinances' compact
            # `[HH:MM:SS] LEVEL: message` shape.
            fmt = "%(message)s"
        except ImportError:
            handlers = [logging.StreamHandler()]
            fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    else:
        handlers = [logging.StreamHandler()]
        fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)


_configure_logging()
logger = logging.getLogger(__name__)


# Match a Granian access log line and capture the request path and status code.
# Granian's default access format is similar to the Apache combined format:
#   <client> [<date>] "<method> <path>[?query] HTTP/x" <status> <bytes>
# The substring match was too loose ("/health" matched "/health-status" too) and
# never inspected the status code. We now require:
#   - exact path match (anchored before ? or whitespace)
#   - status in the canonical position after the closing quote
_ACCESS_LOG_PATTERN = re.compile(
    r'"(?:GET|HEAD|POST|PUT|DELETE|PATCH|OPTIONS)\s+'
    r"(?P<path>[^\s?]+)"
    r'(?:\?[^\s"]*)?\s+[^"]+"\s+'
    r"(?P<status>\d{3})"
)


class HealthCheckLogFilter(logging.Filter):
    """Suppress successful health-check access log lines.

    Docker's healthcheck hits /health every few seconds; logging each line
    buries everything else. Failures (status >= 400) still pass through so a
    flapping liveness check is visible. Mirrors the myfinances request-logger
    behaviour for `/healthz`.
    """

    def __init__(self, paths: tuple[str, ...] = ("/health", "/healthz")) -> None:
        super().__init__()
        self.paths = paths

    def filter(self, record: logging.LogRecord) -> bool:
        match = _ACCESS_LOG_PATTERN.search(record.getMessage())
        if not match:
            return True
        if match.group("path") not in self.paths:
            return True
        try:
            status = int(match.group("status"))
        except ValueError:
            return True
        return status >= 400


logging.getLogger("granian.access").addFilter(HealthCheckLogFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting TideWatch...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize default settings
    async with AsyncSessionLocal() as db:
        await SettingsService.init_defaults(db)
    logger.info("Default settings initialized")

    # Clean up stuck update history records from previous crashes
    from app.services.update_engine import UpdateEngine

    async with AsyncSessionLocal() as db:
        await UpdateEngine.recover_stuck_records(db)

    # Clean up stuck check jobs from previous crashes/GC
    async with AsyncSessionLocal() as db:
        from sqlalchemy import text

        check_result = await db.execute(
            text(
                "UPDATE check_jobs SET status = 'failed', error_message = 'Interrupted by application restart' WHERE status IN ('queued', 'running')"
            )
        )
        check_count: int = check_result.rowcount  # type: ignore[assignment]
        if check_count:
            logger.warning("Cleaned up %d stuck check job(s) from previous run", check_count)
            await db.commit()

        # Same for dependency scan jobs
        scan_result = await db.execute(
            text(
                "UPDATE dependency_scan_jobs SET status = 'failed', error_message = 'Interrupted by application restart' WHERE status IN ('queued', 'running')"
            )
        )
        scan_count: int = scan_result.rowcount  # type: ignore[assignment]
        if scan_count:
            logger.warning(
                "Cleaned up %d stuck dependency scan job(s) from previous run", scan_count
            )
            await db.commit()

    # Recover any VulnForge scan jobs interrupted by previous shutdown
    from app.services.vulnforge_scan_worker import recover_interrupted_jobs

    await recover_interrupted_jobs()

    # Start background scheduler for automatic update checks
    await scheduler_service.start()
    logger.info("Background scheduler started")

    # Warn if authentication is disabled
    async with AsyncSessionLocal() as db:
        auth_mode = await SettingsService.get(db, "auth_mode", default="none")
        if auth_mode == "none":
            logger.warning(
                "⚠️  AUTH_MODE is set to 'none' - Authentication is DISABLED. "
                "All API endpoints are publicly accessible. "
                "Configure auth_mode='local' or 'oidc' in Settings to enable authentication."
            )
        else:
            logger.info(f"Authentication enabled: auth_mode='{auth_mode}'")

    yield

    # Shutdown scheduler
    await scheduler_service.stop()
    logger.info("Shutting down TideWatch...")


# Create FastAPI app
app = FastAPI(
    title="TideWatch",
    description="Intelligent Docker Container Update Manager with Auto-Restart",
    version=get_app_version(),
    lifespan=lifespan,
)

# CORS middleware - Secure defaults for localhost development
# Default CORS origins (localhost development ports)
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://localhost:8788",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8788",
]

# Load CORS origins from environment or use secure defaults
cors_origins_env = os.getenv("CORS_ORIGINS")
if cors_origins_env:
    if cors_origins_env == "*":
        cors_origins = ["*"]
        logger.warning("⚠️  CORS configured with wildcard (*) - not recommended for production")
    else:
        cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
        logger.info(f"CORS origins from environment: {cors_origins}")
else:
    cors_origins = DEFAULT_CORS_ORIGINS
    logger.info(f"Using default CORS origins (localhost development): {len(cors_origins)} origins")

# Validate CORS configuration
if cors_origins == ["*"] and os.getenv("CSRF_SECURE_COOKIE", "false").lower() == "true":
    logger.warning(
        "⚠️  CORS wildcard (*) with allow_credentials=True is not allowed by browsers in production"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    # Cannot use allow_credentials=True with allow_origins=["*"]
    allow_credentials=cors_origins != ["*"],
    # Explicitly list allowed methods instead of wildcard
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    # Explicitly list allowed headers instead of wildcard
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "Accept"],
    expose_headers=["X-CSRF-Token", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# Add rate limiting middleware (60 requests per minute per IP)
# Only enable rate limiting in production (not during tests)
if os.getenv("TIDEWATCH_TESTING", "false").lower() != "true":
    from app.middleware import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
    logger.info("✓ Rate limiting middleware enabled (60 req/min)")
else:
    logger.info("✗ Rate limiting middleware DISABLED (testing mode)")

# CSRF protection middleware
# IMPORTANT: Must be added BEFORE SessionMiddleware because middlewares execute in LIFO order
# (last added = first executed). CSRF needs session to be available, so SessionMiddleware
# must be added after CSRF so it executes before CSRF.
from app.middleware.csrf import CSRFProtectionMiddleware  # noqa: E402

app.add_middleware(CSRFProtectionMiddleware)

# Session middleware for CSRF protection
# Generate/load session secret key from persistent storage
from app.utils.security import is_secure_cookie, sanitize_path  # noqa: E402

try:
    # Validate session secret file path (must be in /data)
    session_secret_file = sanitize_path("/data/session_secret.key", "/data", allow_symlinks=False)

    if session_secret_file.exists():
        session_secret = session_secret_file.read_text().strip()
        logger.info("Loaded existing session secret key")
    else:
        session_secret = secrets.token_urlsafe(32)
        session_secret_file.parent.mkdir(parents=True, exist_ok=True)
        # lgtm[py/clear-text-storage-sensitive-data] - Session secret must persist across restarts
        # File is stored in protected /data/ directory with 0o600 permissions
        session_secret_file.write_text(session_secret)
        session_secret_file.chmod(0o600)
        logger.info("Generated new session secret key")
except (ValueError, FileNotFoundError) as e:
    logger.error(f"Invalid session secret file path: {e}")
    # Fall back to temporary in-memory secret (will change on restart)
    session_secret = secrets.token_urlsafe(32)
    logger.warning("Using temporary in-memory session secret (will invalidate sessions on restart)")

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="tidewatch_session",
    max_age=24 * 60 * 60,  # 24 hours
    same_site="lax",
    https_only=is_secure_cookie(),
)


# Redirect old /api/* paths to /api/v1/* for backward compatibility with frontend
# NOTE: This middleware must be defined FIRST so it executes LAST in the middleware chain
# FastAPI middleware decorators execute in LIFO order (last defined = first executed)
@app.middleware("http")
async def redirect_old_api_paths(request: Request, call_next):
    """Redirect /api/* to /api/v1/* for backward compatibility."""
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/v1/"):
        # Rewrite path to include v1
        new_path = path.replace("/api/", "/api/v1/", 1)
        # Update the request scope
        request.scope["path"] = new_path
    response = await call_next(request)
    return response


# Security Headers Middleware
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses.

    Headers added:
    - X-Content-Type-Options: nosniff (prevents MIME sniffing)
    - X-Frame-Options: DENY (prevents clickjacking)
    - X-XSS-Protection: 1; mode=block (legacy XSS protection for older browsers)
    - Strict-Transport-Security: HSTS (forces HTTPS in production)
    - Content-Security-Policy: restricts resource loading
    """
    response = await call_next(request)

    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"

    # Legacy XSS protection for older browsers
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # HSTS - only in production with HTTPS
    if is_secure_cookie():
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Content Security Policy
    # Note: This is a basic policy. Adjust based on your frontend requirements.
    csp_directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",  # Needed for inline styles
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",  # Redundant with X-Frame-Options but good defense in depth
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

    return response


# Global Exception Handler
from fastapi.responses import JSONResponse  # noqa: E402


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Generic exception handler to prevent stack trace exposure.

    Security: This prevents internal application details (file paths,
    library versions, code structure) from being exposed in error responses.

    In DEBUG mode (TIDEWATCH_DEBUG=true), detailed errors are shown for development.
    In production, generic error messages are returned.

    All errors are still logged internally with full details for debugging.
    """
    from app.utils.security import sanitize_log_message

    # Log full error details internally (sanitize any user input)
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {sanitize_log_message(str(exc))}",
        exc_info=True,
        extra={
            "path": request.url.path,
            "method": request.method,
            "client": request.client.host if request.client else "unknown",
        },
    )

    # Return generic error message unless debug mode
    if os.getenv("TIDEWATCH_DEBUG", "false").lower() == "true":
        # Development mode - show detailed error
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "type": type(exc).__name__, "debug": True},
        )

    # Production mode - generic error message
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please contact support if this persists."},
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "tidewatch"}


# Prometheus metrics endpoint (full — via prometheus_client library)
# For a lightweight subset, see also GET /api/v1/system/metrics
@app.get("/metrics")
async def metrics():
    """Full Prometheus metrics endpoint using the prometheus_client library.

    This is the primary scrape target for Prometheus. Includes detailed histograms,
    gauges, and counters. For a lightweight subset (container/update counts only),
    use GET /api/v1/system/metrics.
    """
    from app.database import AsyncSessionLocal
    from app.services.metrics import collect_metrics, get_content_type, get_metrics

    # Collect current metrics from database
    async with AsyncSessionLocal() as db:
        await collect_metrics(db)

    # Return Prometheus-formatted metrics
    return Response(content=get_metrics(), media_type=get_content_type())


# API routes
from app.routes import api_router  # noqa: E402

app.include_router(api_router)

# Serve frontend static files (in production)

static_dir = Path("/app/static")

if static_dir.exists():
    # Serve static assets (CSS, JS, images).
    #
    # Vite emits content-hashed filenames under /assets (e.g. main-abc123.js),
    # which are immutable for the life of the build. The `immutable` directive
    # plus a year-long max-age stops browsers and Cloudflare from revalidating
    # these on every navigation — the source of most post-deploy reload latency.
    class ImmutableStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    app.mount(
        "/assets",
        ImmutableStaticFiles(directory=str(static_dir / "assets")),
        name="assets",
    )

    # Serve frontend
    from fastapi.responses import FileResponse, JSONResponse

    @app.get("/")
    async def serve_index():
        """Serve frontend index.html at root."""
        return FileResponse(static_dir / "index.html")

    # PWA-style assets that live in `frontend/public/` (and therefore get
    # copied to the root of `dist/` by Vite). These have to be explicit
    # because the 404 fallback below would otherwise serve `index.html`
    # for unknown paths — and the service worker registration will fail
    # if `/sw.js` returns HTML instead of JavaScript.
    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(
            static_dir / "sw.js",
            media_type="application/javascript",
            # The SW script itself must not be long-cached, otherwise we
            # can't ship updates. Browsers also limit SW script caching
            # to a max of 24h by default since Chrome 68.
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/offline.html", include_in_schema=False)
    async def offline_page():
        return FileResponse(static_dir / "offline.html", media_type="text/html")

    # SPA fallback - handle 404s by serving index.html for client-side routing
    @app.exception_handler(404)
    async def spa_404_handler(request, exc):
        """Return index.html for 404s (SPA fallback), except for API routes."""
        # For API routes, return actual 404 with detail from HTTPException
        if request.url.path.startswith("/api/"):
            # Preserve detail message from HTTPException if available
            detail = getattr(exc, "detail", "Not Found")
            return JSONResponse(status_code=404, content={"detail": detail})

        # For static files that don't exist, try index.html
        return FileResponse(static_dir / "index.html")
else:
    # Development mode - show API docs as root
    @app.get("/")
    async def root():
        return {
            "message": "TideWatch API",
            "docs": "/docs",
            "health": "/health",
        }


if __name__ == "__main__":
    import subprocess
    import sys

    # Use same server as production (Granian) for consistency
    cmd = [
        "granian",
        "--interface",
        "asgi",
        "--host",
        "0.0.0.0",
        "--port",
        "8788",
        "--reload",  # Auto-reload for development
        "app.main:app",
    ]

    sys.exit(subprocess.run(cmd).returncode)
