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
        autocommit=False,
    )

    async with async_session_maker() as session:
        # Don't manually begin transaction - let SQLAlchemy manage it
        # This allows commits within fixtures to actually persist
        yield session
        # Rollback any uncommitted changes
        await session.rollback()


@pytest.fixture
def mock_async_session_local(db):
    """Mock AsyncSessionLocal to return test database session.

    This fixture is essential for testing services that create their own
    database sessions using AsyncSessionLocal() (like scheduler, restart_scheduler).
    It ensures they use the test's in-memory database instead of trying to
    access the production database.

    Usage:
        @pytest.mark.asyncio
        async def test_something(db, mock_async_session_local):
            # Service will now use the test db when it calls AsyncSessionLocal()
            await scheduler_service.start()
    """
    from unittest.mock import MagicMock, patch

    class MockAsyncSessionLocal:
        """Mock async context manager for database sessions."""

        def __call__(self):
            """Return self to act as context manager."""
            return self

        async def __aenter__(self):
            """Enter context manager, return test db session."""
            return db

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            """Exit context manager."""
            # Don't close the session - let the test fixture manage it
            return False

    # Create instance of mock
    mock_session_local = MockAsyncSessionLocal()

    # Patch all AsyncSessionLocal imports in scheduler-related modules
    with patch('app.services.scheduler.AsyncSessionLocal', mock_session_local), \
         patch('app.services.restart_scheduler.AsyncSessionLocal', mock_session_local):
        yield mock_session_local


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
def make_container():
    """Factory fixture to create Container instances with valid required fields.

    Usage:
        container = make_container(name="my-container", image="nginx:1.20")

    All required fields have sensible defaults:
    - registry: "docker.io"
    - compose_file: "/compose/test.yml"
    - service_name: Derived from name or "test-service"
    """
    def _make_container(**kwargs):
        from app.models.container import Container

        # Set defaults for required fields
        defaults = {
            "image": "nginx",  # Default image if not provided
            "current_tag": "latest",  # Default tag if not provided
            "registry": "docker.io",
            "compose_file": "/compose/test.yml",
            "service_name": kwargs.get("name", "test-service"),
        }

        # Merge defaults with provided kwargs (kwargs take precedence)
        container_data = {**defaults, **kwargs}

        # Remove 'status' if accidentally provided (not a valid field)
        container_data.pop("status", None)

        return Container(**container_data)

    return _make_container


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
def make_update():
    """Factory fixture to create Update instances with valid required fields.

    Usage:
        update = make_update(container_id=1, from_tag="1.0", to_tag="1.1")

    All required fields have sensible defaults:
    - container_name: Derived from container_id or "test-container"
    - registry: "docker.io"
    - reason_type: "update"
    """
    def _make_update(**kwargs):
        from app.models.update import Update

        # Set defaults for required fields
        defaults = {
            "container_name": f"container-{kwargs.get('container_id', 1)}",
            "registry": "docker.io",
            "reason_type": "update",
        }

        # Merge defaults with provided kwargs (kwargs take precedence)
        update_data = {**defaults, **kwargs}

        # Map legacy field names to correct ones
        if "current_tag" in update_data:
            update_data["from_tag"] = update_data.pop("current_tag")
        if "new_tag" in update_data:
            update_data["to_tag"] = update_data.pop("new_tag")

        return Update(**update_data)

    return _make_update


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
    # Set JWT token for authentication (must match login endpoint's token format)
    token = create_access_token({
        "sub": "admin",  # TideWatch uses "admin" as the subject
        "username": admin_user["username"]
    })
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
