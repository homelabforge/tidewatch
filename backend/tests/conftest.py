"""Pytest configuration and fixtures."""

import os
import asyncio
import pytest
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Set DATABASE_URL for tests BEFORE importing app.db
# This prevents the module from trying to create /data directory
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

# Set encryption key for tests
from cryptography.fernet import Fernet
if "TIDEWATCH_ENCRYPTION_KEY" not in os.environ:
    os.environ["TIDEWATCH_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

# Disable rate limiting during tests
os.environ["TIDEWATCH_TESTING"] = "true"

from app.db import Base
from app.models import *  # Import all models to ensure they're registered
from app.services.auth import hash_password, create_access_token
from app.services.settings_service import SettingsService


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def db_engine():
    """Create a test database engine."""
    # Use in-memory SQLite for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    await engine.dispose()


@pytest.fixture(scope="function")
async def db(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with automatic rollback."""
    async_session_maker = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with async_session_maker() as session:
        # Start transaction manually (not using context manager)
        # so we can rollback in finally block
        await session.begin()
        try:
            yield session
        finally:
            # Always rollback to ensure clean state for next test
            await session.rollback()


@pytest.fixture
def sample_container_data():
    """Sample container data for testing."""
    return {
        "name": "test-container",
        "image": "nginx:1.20",
        "current_tag": "1.20",
        "compose_file": "/compose/test.yml",
        "service_name": "test-service",
        "registry": "docker.io",
        "policy": "manual",
    }


@pytest.fixture
def sample_update_data():
    """Sample update data for testing."""
    return {
        "container_id": 1,
        "from_tag": "1.20",
        "to_tag": "1.21",
        "status": "pending",
        "reason_type": "update",
        "reason_summary": "New version available",
    }


@pytest.fixture
async def app():
    """Create FastAPI app for testing."""
    from app.main import app as application
    return application


@pytest.fixture
async def client(app, db):
    """Create async test client with auth disabled by default (auth_mode='none')."""
    from httpx import AsyncClient, ASGITransport
    from app.db import get_db

    # Override get_db dependency to use test database
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def admin_user(db):
    """Create admin credentials in settings for authentication tests."""
    # Set admin credentials in settings (TideWatch uses settings-based auth)
    password_hash = hash_password("AdminPassword123!")
    await SettingsService.set(db, "admin_username", "admin")
    await SettingsService.set(db, "admin_email", "admin@example.com")
    await SettingsService.set(db, "admin_password_hash", password_hash)
    await SettingsService.set(db, "admin_full_name", "Admin User")

    # Enable local authentication (required for require_auth to work properly)
    await SettingsService.set(db, "auth_mode", "local")

    await db.commit()

    # Return dict with admin info (matching TideWatch's single-user model)
    return {
        "username": "admin",
        "email": "admin@example.com",
        "password": "AdminPassword123!",
        "full_name": "Admin User"
    }


@pytest.fixture
async def authenticated_client(client, admin_user):
    """AsyncClient with valid JWT token and CSRF token."""
    # Set JWT token for authentication
    token = create_access_token({"sub": admin_user["username"]})
    client.headers = {"Authorization": f"Bearer {token}"}

    # Get CSRF token by making a GET request
    response = await client.get("/api/v1/settings")
    if "X-CSRF-Token" in response.headers:
        csrf_token = response.headers["X-CSRF-Token"]
        # Add CSRF token to headers for subsequent requests
        client.headers["X-CSRF-Token"] = csrf_token

    return client


@pytest.fixture
def mock_docker_client():
    """Mock Docker client for container operations."""
    from unittest.mock import MagicMock, patch
    with patch('docker.from_env') as mock:
        docker_client = MagicMock()
        mock.return_value = docker_client
        yield docker_client


@pytest.fixture
def mock_event_bus():
    """Mock event bus for testing notifications."""
    from unittest.mock import patch, AsyncMock
    with patch('app.services.event_bus.event_bus') as mock:
        mock.publish = AsyncMock()
        yield mock


@pytest.fixture
def notification_event():
    """Sample notification event."""
    return {
        "type": "update_available",
        "container_name": "nginx",
        "current_version": "1.20",
        "new_version": "1.21",
        "timestamp": "2025-01-01T00:00:00Z"
    }


@pytest.fixture
def mock_httpx_client():
    """Mock httpx client for notification services."""
    from unittest.mock import patch, AsyncMock, MagicMock
    with patch('httpx.AsyncClient') as mock:
        mock_instance = AsyncMock()
        mock.return_value.__aenter__.return_value = mock_instance
        mock_instance.post = AsyncMock(return_value=MagicMock(status_code=200))
        yield mock_instance


@pytest.fixture
def mock_smtp_client():
    """Mock SMTP client for email notifications."""
    from unittest.mock import patch
    with patch('aiosmtplib.SMTP') as mock:
        yield mock
