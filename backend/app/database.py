"""Database configuration and session management."""

import logging
import os
import sqlite3
from collections.abc import AsyncGenerator
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.utils.security import sanitize_path

logger = logging.getLogger(__name__)


# Replace Python's deprecated default sqlite3 datetime adapter/converter with
# ISO-8601 versions. The stdlib default was deprecated in Python 3.12 and will
# be removed in a future release; registering our own now silences the warning
# and future-proofs the schema. SQLAlchemy normally bypasses these for typed
# columns, but aiosqlite still trips the default-adapter deprecation on import.
sqlite3.register_adapter(date, lambda v: v.isoformat())
sqlite3.register_adapter(datetime, lambda v: v.isoformat())
sqlite3.register_converter("date", lambda v: date.fromisoformat(v.decode()))
sqlite3.register_converter("datetime", lambda v: datetime.fromisoformat(v.decode()))

# Database URL from environment or default
# Default to /data/tidewatch.db (production path mounted as volume)
# Can override with DATABASE_URL environment variable if needed
default_db = "sqlite+aiosqlite:////data/tidewatch.db"
DATABASE_URL = os.getenv("DATABASE_URL", default_db)

# Ensure database directory exists (skip for in-memory databases used in tests)
if DATABASE_URL.startswith("sqlite") and ":memory:" not in DATABASE_URL:
    # Extract path from URL (handle both sqlite:/// and sqlite://)
    db_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite+aiosqlite://", "")

    # Validate database path to prevent path traversal
    # Allow /data directory for production and /tmp for tests
    try:
        if db_path.startswith("/data/"):
            validated_path = sanitize_path(db_path, "/data", allow_symlinks=False)
        elif db_path.startswith("/tmp/"):
            validated_path = sanitize_path(db_path, "/tmp", allow_symlinks=False)
        else:
            # For relative paths or other locations, validate against current directory
            validated_path = Path(db_path).resolve()

        db_dir = validated_path.parent
        if db_dir and str(db_dir) != ".":
            db_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, FileNotFoundError) as e:
        logger.error(f"Invalid database path: {db_path} - {e}")
        raise ValueError(f"Invalid DATABASE_URL path: {e}")

# Create async engine with WAL mode for better concurrency
# Configure connection pooling based on database type
# SQLite doesn't benefit from connection pooling and should use minimal pool
# PostgreSQL/MySQL benefit from larger pools for concurrent connections
if "sqlite" in DATABASE_URL:
    # Pool choice is load-bearing for correctness under the async scheduler:
    #
    # - In-memory SQLite (tests) MUST use StaticPool. Each new connection opens
    #   a *private* in-memory database, so a single shared connection is the
    #   only way the schema created at startup stays visible to later queries.
    #
    # - File-backed SQLite (production) uses NullPool so every AsyncSession gets
    #   its OWN connection. StaticPool's single shared connection is unsafe here:
    #   concurrent scheduler jobs (e.g. the 6h update check colliding with the
    #   */5 auto-apply tick) interleave statements on the one connection and
    #   corrupt each other's transaction view — which surfaced as
    #   "InvalidRequestError: Could not refresh instance" and silently killed
    #   every scheduled update check. NullPool isolates sessions; WAL plus a
    #   per-connection busy_timeout (below) handle SQLite's single-writer lock.
    from sqlalchemy.pool import NullPool, StaticPool

    is_memory = ":memory:" in DATABASE_URL

    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if is_memory else NullPool,
    )

    # Apply SQLite tuning on EVERY new connection. With NullPool each session
    # opens a fresh connection, so per-connection pragmas (busy_timeout,
    # synchronous, cache_size, foreign_keys) must be (re)set here — otherwise a
    # new connection silently reverts to busy_timeout=0 and raises
    # "database is locked" the moment two writers contend. journal_mode=WAL is
    # database-level/persistent, but re-asserting it is idempotent and keeps the
    # full configuration self-contained in one place.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        try:
            # busy_timeout first so the pragmas below wait out any brief lock.
            cursor.execute("PRAGMA busy_timeout=5000")
            if not is_memory:
                # WAL/synchronous/cache are meaningless (and WAL errors) on
                # :memory:, which is always an in-RAM journal.
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=-64000")  # negative = KB → 64MB
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

else:
    # PostgreSQL/MySQL: Use connection pooling for better performance
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,  # Default pool size for concurrent connections
        max_overflow=20,  # Allow up to 20 additional connections during peak load
        pool_timeout=30,  # Wait up to 30s for connection before timing out
        pool_recycle=3600,  # Recycle connections after 1 hour to prevent stale connections
        pool_pre_ping=True,  # Verify connection is alive before using it
    )

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Dependency for getting database sessions."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Initialize database tables and run pending migrations."""
    # First, create base tables. SQLite tuning (WAL, synchronous, cache_size,
    # busy_timeout, foreign_keys) is applied per-connection via the engine
    # "connect" hook above, so it is already in effect for this connection and
    # every session connection that follows.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if "sqlite" in DATABASE_URL and ":memory:" not in DATABASE_URL:
        logger.info(
            "SQLite optimizations applied per-connection: "
            "WAL mode, NORMAL sync, 64MB cache, 5s busy timeout, FK enforcement"
        )

    # Run pending migrations — fail-fast so we don't run with a broken schema
    from app.migrations.runner import run_migrations

    migrations_dir = Path(__file__).parent / "migrations"
    await run_migrations(engine, migrations_dir)

    # Dispose of any leftover connections from initialization
    await engine.dispose()
