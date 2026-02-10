"""TideWatch - Intelligent Docker Container Update Manager."""

import logging
import os
import secrets
import tomllib
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.database import AsyncSessionLocal, init_db
from app.services.scheduler import scheduler_service
from app.services.settings_service import SettingsService


def get_version() -> str:
    """Read version from pyproject.toml (single source of truth)."""
    try:
        # Safely construct path relative to this file
        # pyproject.toml is in backend/ directory (parent of app/)
        app_dir = Path(__file__).parent.resolve()
        backend_dir = app_dir.parent.resolve()
        pyproject_path = backend_dir / "pyproject.toml"

        # Verify path is within expected directory to prevent path traversal
        # (pyproject.toml should be in /app or /app/backend in production)
        if not pyproject_path.exists():
            logger.warning(f"pyproject.toml not found at {pyproject_path}")
            return "0.0.0-dev"

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except (FileNotFoundError, KeyError) as e:
        logger.warning(f"Could not read version from pyproject.toml: {e}")
        return "0.0.0-dev"


# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Filter to exclude health check endpoints from access logs
class EndpointFilter(logging.Filter):
    """Filter to exclude specific endpoints from Granian access logs."""

    def __init__(self, excluded_paths: list[str]) -> None:
        super().__init__()
        self.excluded_paths = excluded_paths

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False if the log record is for an excluded endpoint."""
        # Granian access logs have the path in the message
        message = record.getMessage()
        return not any(path in message for path in self.excluded_paths)


# Apply filter to granian access logger to exclude health checks
logging.getLogger("granian.access").addFilter(EndpointFilter(["/health"]))


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
    # Using raw SQL to avoid issues with model columns that may not exist yet during migrations
    async with AsyncSessionLocal() as db:
        from datetime import datetime

        from sqlalchemy import text

        # Find all in_progress records using raw SQL
        result = await db.execute(
            text("SELECT id FROM update_history WHERE status = :status"),
            {"status": "in_progress"},
        )
        stuck_records = result.fetchall()

        if stuck_records:
            logger.warning(
                f"Found {len(stuck_records)} stuck update history records, marking as failed"
            )
            # Update records using raw SQL
            await db.execute(
                text("""
                    UPDATE update_history
                    SET status = :new_status,
                        error_message = :error_msg,
                        completed_at = :completed_at
                    WHERE status = :old_status
                """),
                {
                    "new_status": "failed",
                    "error_msg": "Update interrupted by application restart",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "old_status": "in_progress",
                },
            )
            await db.commit()
            logger.info(f"Cleaned up {len(stuck_records)} stuck update history records")

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
    version=get_version(),
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
from app.utils.security import sanitize_path  # noqa: E402

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
    https_only=False,  # Set to True if using HTTPS in production
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
    if os.getenv("CSRF_SECURE_COOKIE", "false").lower() == "true":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Content Security Policy
    # Note: This is a basic policy. Adjust based on your frontend requirements.
    csp_directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # Adjust based on React requirements
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


# Prometheus metrics endpoint
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
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
    # Serve static assets (CSS, JS, images)
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    # Serve frontend
    from fastapi.responses import FileResponse, JSONResponse

    @app.get("/")
    async def serve_index():
        """Serve frontend index.html at root."""
        return FileResponse(static_dir / "index.html")

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
