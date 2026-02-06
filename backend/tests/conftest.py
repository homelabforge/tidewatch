"""Pytest configuration and fixtures."""

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
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

from app.database import Base
from app.models import *  # noqa: F403 - Import all models to ensure they're registered
from app.services.auth import create_access_token, hash_password
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
async def db(db_engine) -> AsyncGenerator[AsyncSession]:
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
    from unittest.mock import patch

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
    with (
        patch("app.services.scheduler.AsyncSessionLocal", mock_session_local),
        patch("app.services.restart_scheduler.AsyncSessionLocal", mock_session_local),
    ):
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
            "from_tag": "1.0.0",  # Default from tag
            "to_tag": "1.1.0",  # Default to tag
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
    from httpx import ASGITransport, AsyncClient

    from app.database import get_db

    # Override get_db dependency to use test database
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    ) as ac:
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
    await SettingsService.set(db, "admin_auth_method", "local")

    # Enable local authentication (required for require_auth to work properly)
    await SettingsService.set(db, "auth_mode", "local")

    await db.commit()

    # Return dict with admin info (matching TideWatch's single-user model)
    return {
        "username": "admin",
        "email": "admin@example.com",
        "password": "AdminPassword123!",
        "full_name": "Admin User",
    }


@pytest.fixture
async def authenticated_client(client, admin_user):
    """AsyncClient with valid JWT token and CSRF token."""
    # Set JWT token for authentication (must match login endpoint's token format)
    token = create_access_token(
        {
            "sub": "admin",  # TideWatch uses "admin" as the subject
            "username": admin_user["username"],
        }
    )
    client.headers = {"Authorization": f"Bearer {token}"}

    # Get CSRF token by making a GET request
    response = await client.get("/api/v1/settings")
    if "X-CSRF-Token" in response.headers:
        csrf_token = response.headers["X-CSRF-Token"]
        # Add CSRF token to headers for subsequent requests
        client.headers["X-CSRF-Token"] = csrf_token

    return client


class MockDockerContainer:
    """Mock Docker container with state machine for testing."""

    def __init__(
        self,
        id: str,
        name: str,
        image: str,
        status: str = "running",
        labels: dict | None = None,
    ):
        self.id = id
        self.name = name
        self.image = image
        self.status = status
        self.labels = labels or {}
        self.attrs = {
            "Id": id,
            "Name": name if name.startswith("/") else f"/{name}",
            "State": {
                "Status": status,
                "Running": status == "running",
                "Paused": status == "paused",
                "Restarting": False,
                "OOMKilled": False,
                "Dead": False,
                "Pid": 12345 if status == "running" else 0,
                "ExitCode": 0,
                "StartedAt": "2025-01-01T00:00:00.000000000Z",
                "FinishedAt": "0001-01-01T00:00:00Z"
                if status == "running"
                else "2025-01-01T01:00:00.000000000Z",
            },
            "Config": {
                "Image": image,
                "Labels": self.labels,
                "Hostname": name,
            },
            "Image": f"sha256:{'0' * 64}",
        }

    def start(self):
        """Start the container."""
        if self.status in ["exited", "created"]:
            self.status = "running"
            self.attrs["State"]["Status"] = "running"
            self.attrs["State"]["Running"] = True
            self.attrs["State"]["Pid"] = 12345

    def stop(self, timeout=10):
        """Stop the container."""
        if self.status == "running":
            self.status = "exited"
            self.attrs["State"]["Status"] = "exited"
            self.attrs["State"]["Running"] = False
            self.attrs["State"]["Pid"] = 0

    def restart(self, timeout=10):
        """Restart the container."""
        self.stop(timeout)
        self.status = "restarting"
        self.attrs["State"]["Status"] = "restarting"
        self.attrs["State"]["Restarting"] = True
        # Simulate restart completion
        self.start()
        self.attrs["State"]["Restarting"] = False

    def pause(self):
        """Pause the container."""
        if self.status == "running":
            self.status = "paused"
            self.attrs["State"]["Status"] = "paused"
            self.attrs["State"]["Paused"] = True

    def unpause(self):
        """Unpause the container."""
        if self.status == "paused":
            self.status = "running"
            self.attrs["State"]["Status"] = "running"
            self.attrs["State"]["Paused"] = False

    def remove(self, force=False):
        """Remove the container."""
        import docker.errors

        if self.status == "running" and not force:
            raise docker.errors.APIError("Cannot remove running container without force=True")
        # Container would be removed from the client's list

    def reload(self):
        """Reload container state from daemon (no-op in mock)."""
        pass


class MockDockerClient:
    """Enhanced mock Docker client for comprehensive testing."""

    def __init__(self):
        self._containers = []
        self._images = []
        self._volumes = []
        self._networks = []

        # Container management
        from unittest.mock import MagicMock

        self.containers = MagicMock()
        self.images = MagicMock()
        self.volumes = MagicMock()
        self.networks = MagicMock()

        # Wire up container methods
        self.containers.list = self._list_containers
        self.containers.get = self._get_container
        self.containers.run = self._run_container
        self.containers.create = self._create_container

        # Wire up image methods
        self.images.list = MagicMock(return_value=self._images)
        self.images.get = MagicMock(side_effect=self._get_image)

        # Wire up volume methods
        self.volumes.list = MagicMock(return_value=self._volumes)

        # Wire up network methods
        self.networks.list = MagicMock(return_value=self._networks)

    def _list_containers(self, all=False, filters=None):
        """List containers with optional filters."""
        containers = self._containers.copy()

        # Apply status filter
        if filters and "status" in filters:
            statuses = (
                filters["status"] if isinstance(filters["status"], list) else [filters["status"]]
            )
            containers = [c for c in containers if c.status in statuses]

        # Apply label filter
        if filters and "label" in filters:
            labels = filters["label"] if isinstance(filters["label"], list) else [filters["label"]]
            containers = [
                c
                for c in containers
                if any(f"{k}={v}" in labels or k in labels for k, v in c.labels.items())
            ]

        # Apply name filter
        if filters and "name" in filters:
            names = filters["name"] if isinstance(filters["name"], list) else [filters["name"]]
            containers = [c for c in containers if any(n in c.name for n in names)]

        # Filter by running status if all=False
        if not all:
            containers = [c for c in containers if c.status == "running"]

        return containers

    def _get_container(self, container_id):
        """Get a container by ID or name."""
        import docker.errors

        for container in self._containers:
            if container.id == container_id or container.name == container_id:
                return container
        raise docker.errors.NotFound(f"Container {container_id} not found")

    def _run_container(self, image, **kwargs):
        """Create and start a container."""
        container = self._create_container(image, **kwargs)
        container.start()
        return container

    def _create_container(self, image, **kwargs):
        """Create a container."""
        import secrets

        container_id = secrets.token_hex(32)
        name = kwargs.get("name", f"container-{len(self._containers)}")
        labels = kwargs.get("labels", {})

        container = MockDockerContainer(container_id, name, image, status="created", labels=labels)
        self._containers.append(container)
        return container

    def _get_image(self, image_name):
        """Get an image by name."""
        import docker.errors

        for image in self._images:
            if image_name in getattr(image, "tags", []):
                return image
        raise docker.errors.ImageNotFound(f"Image {image_name} not found")

    def add_container(
        self,
        id: str,
        name: str,
        image: str,
        status: str = "running",
        labels: dict | None = None,
    ):
        """Helper to add a mock container for testing."""
        container = MockDockerContainer(id, name, image, status, labels)
        self._containers.append(container)
        return container

    def add_image(self, tags: list, id: str | None = None):
        """Helper to add a mock image for testing."""
        from unittest.mock import MagicMock

        image = MagicMock()
        image.id = id or f"sha256:{'0' * 64}"
        image.tags = tags
        self._images.append(image)
        return image

    def ping(self):
        """Ping the Docker daemon."""
        return True

    def version(self):
        """Get Docker daemon version info."""
        return {
            "Version": "24.0.0",
            "ApiVersion": "1.43",
            "Platform": {"Name": "Docker Engine - Community"},
        }

    def info(self):
        """Get Docker daemon system info."""
        return {
            "Containers": len(self._containers),
            "ContainersRunning": len([c for c in self._containers if c.status == "running"]),
            "ContainersPaused": len([c for c in self._containers if c.status == "paused"]),
            "ContainersStopped": len([c for c in self._containers if c.status == "exited"]),
            "Images": len(self._images),
        }


@pytest.fixture
def mock_docker_client():
    """Enhanced mock Docker client for container operations.

    Provides a comprehensive mock with:
    - Container state management (running, stopped, paused)
    - Container lifecycle operations (start, stop, restart, remove)
    - Container filtering by status, labels, name
    - Helper methods to add test containers and images

    Usage:
        def test_example(mock_docker_client):
            # Add test containers
            container = mock_docker_client.add_container("abc123", "nginx", "nginx:latest")

            # Use as Docker client
            containers = mock_docker_client.containers.list()
            assert len(containers) == 1
    """
    return MockDockerClient()


@pytest.fixture
def mock_event_bus():
    """Mock event bus for testing notifications."""
    from unittest.mock import AsyncMock, patch

    with patch("app.services.event_bus.event_bus") as mock:
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
        "timestamp": "2025-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_httpx_client():
    """Mock httpx client for notification services."""
    from unittest.mock import AsyncMock, MagicMock, patch

    with patch("httpx.AsyncClient") as mock:
        mock_instance = AsyncMock()
        mock.return_value.__aenter__.return_value = mock_instance
        mock_instance.post = AsyncMock(return_value=MagicMock(status_code=200))
        yield mock_instance


@pytest.fixture
def mock_smtp_client():
    """Mock SMTP client for email notifications."""
    from unittest.mock import patch

    with patch("aiosmtplib.SMTP") as mock:
        yield mock
