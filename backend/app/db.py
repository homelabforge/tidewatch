"""Database configuration and session management."""

import os
import logging
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.utils.security import sanitize_path

logger = logging.getLogger(__name__)

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
    # SQLite: Use StaticPool for better performance
    # StaticPool maintains a single connection, better than NullPool which recreates connections
    # This reduces connection overhead while avoiding SQLite's locking issues
    from sqlalchemy.pool import StaticPool
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Single persistent connection for SQLite
        pool_reset_on_return=None,  # Don't reset connections on return for SQLite
    )
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


async def get_db() -> AsyncSession:
    """Dependency for getting database sessions."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Initialize database tables and run pending migrations."""
    # First, create base tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Enable WAL mode and optimizations for SQLite
        if "sqlite" in DATABASE_URL:
            # WAL mode allows concurrent reads/writes
            await conn.execute(text("PRAGMA journal_mode=WAL"))

            # NORMAL synchronous is safe with WAL and faster than FULL
            await conn.execute(text("PRAGMA synchronous=NORMAL"))

            # Increase cache size (negative = KB, -64000 = 64MB)
            await conn.execute(text("PRAGMA cache_size=-64000"))

            # Set busy timeout to 5 seconds to handle concurrent access
            await conn.execute(text("PRAGMA busy_timeout=5000"))

            # Enable foreign keys
            await conn.execute(text("PRAGMA foreign_keys=ON"))

            logger.info("SQLite optimizations applied: WAL mode, 64MB cache, 5s busy timeout")

    # Run pending migrations
    try:
        from app.migrations.runner import run_migrations

        migrations_dir = Path(__file__).parent / "migrations"
        await run_migrations(engine, migrations_dir)
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        # Don't fail startup - log error and continue

    # Dispose of any leftover connections from initialization
    await engine.dispose()
