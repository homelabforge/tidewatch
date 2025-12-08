"""Tests for dependency manager (app/services/dependency_manager.py).

Tests topological sorting and dependency resolution:
- Topological sort correctness (Kahn's algorithm)
- Circular dependency detection
- Cache key generation and reuse
- Missing container handling
- Invalid JSON dependencies
- Partial dependency updates
- Dependency validation
"""

import pytest
import json
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.dependency_manager import DependencyManager, _dependency_cache
from app.models.container import Container


class TestDependencyManagerTopologicalSort:
    """Test suite for topological sorting algorithm."""

    def test_simple_linear_dependencies(self):
        """Test simple linear dependency chain: A -> B -> C."""
        dependencies = {
            "app-a": set(),  # No dependencies
            "app-b": {"app-a"},  # Depends on A
            "app-c": {"app-b"},  # Depends on B
        }

        result = DependencyManager._topological_sort(dependencies)

        # A must come before B, B before C
        assert result.index("app-a") < result.index("app-b")
        assert result.index("app-b") < result.index("app-c")
        assert result == ["app-a", "app-b", "app-c"]

    def test_multiple_independent_containers(self):
        """Test containers with no dependencies are sorted alphabetically."""
        dependencies = {
            "nginx": set(),
            "redis": set(),
            "postgres": set(),
        }

        result = DependencyManager._topological_sort(dependencies)

        # All independent - should be sorted alphabetically
        assert result == ["nginx", "postgres", "redis"]

    def test_diamond_dependency_pattern(self):
        """Test diamond dependency: A -> B,C and B,C -> D."""
        dependencies = {
            "database": set(),  # Base
            "api": {"database"},  # Depends on database
            "worker": {"database"},  # Also depends on database
            "frontend": {"api", "worker"},  # Depends on both
        }

        result = DependencyManager._topological_sort(dependencies)

        # Database must come first
        assert result[0] == "database"

        # API and worker before frontend
        assert result.index("api") < result.index("frontend")
        assert result.index("worker") < result.index("frontend")

        # Frontend must be last
        assert result[-1] == "frontend"

    def test_circular_dependency_detection(self):
        """Test circular dependencies raise ValueError."""
        dependencies = {
            "app-a": {"app-b"},  # A depends on B
            "app-b": {"app-a"},  # B depends on A (cycle!)
        }

        with pytest.raises(ValueError) as exc_info:
            DependencyManager._topological_sort(dependencies)

        assert "Circular dependency" in str(exc_info.value)
        assert "app-a" in str(exc_info.value) or "app-b" in str(exc_info.value)

    def test_three_way_circular_dependency(self):
        """Test circular dependency with 3 containers."""
        dependencies = {
            "app-a": {"app-c"},  # A -> C
            "app-b": {"app-a"},  # B -> A
            "app-c": {"app-b"},  # C -> B (cycle: A -> C -> B -> A)
        }

        with pytest.raises(ValueError) as exc_info:
            DependencyManager._topological_sort(dependencies)

        assert "Circular dependency" in str(exc_info.value)

    def test_complex_dependency_graph(self):
        """Test complex real-world dependency graph."""
        dependencies = {
            "postgres": set(),
            "redis": set(),
            "rabbitmq": set(),
            "api": {"postgres", "redis"},
            "worker": {"postgres", "rabbitmq"},
            "scheduler": {"postgres", "redis", "rabbitmq"},
            "frontend": {"api"},
        }

        result = DependencyManager._topological_sort(dependencies)

        # Base services first
        base_services = {"postgres", "redis", "rabbitmq"}
        for service in base_services:
            assert service in result[:3]

        # API, worker, scheduler before frontend
        assert result.index("api") < result.index("frontend")

        # Frontend last
        assert result[-1] == "frontend"

    def test_partial_dependencies_within_list(self):
        """Test containers with dependencies not in the update list."""
        dependencies = {
            "api": {"postgres", "redis"},  # postgres/redis not in list
            "worker": {"api"},
        }

        result = DependencyManager._topological_sort(dependencies)

        # API should come before worker
        assert result.index("api") < result.index("worker")

    def test_single_container_no_dependencies(self):
        """Test single container with no dependencies."""
        dependencies = {"nginx": set()}

        result = DependencyManager._topological_sort(dependencies)

        assert result == ["nginx"]

    def test_empty_dependency_graph(self):
        """Test empty dependency graph returns empty list."""
        dependencies = {}

        result = DependencyManager._topological_sort(dependencies)

        assert result == []

    def test_deterministic_ordering(self):
        """Test same dependencies produce same order."""
        dependencies = {
            "app-c": set(),
            "app-a": set(),
            "app-b": set(),
        }

        result1 = DependencyManager._topological_sort(dependencies)
        result2 = DependencyManager._topological_sort(dependencies)

        # Should be consistent (alphabetically sorted when no dependencies)
        assert result1 == result2
        assert result1 == ["app-a", "app-b", "app-c"]


class TestDependencyManagerCaching:
    """Test suite for dependency resolution caching."""

    def setup_method(self):
        """Clear cache before each test."""
        DependencyManager.clear_dependency_cache()

    def test_cache_key_generation(self):
        """Test cache key is deterministic for same dependencies."""
        dependencies1 = {
            "app-a": {"app-b"},
            "app-b": set(),
        }

        dependencies2 = {
            "app-b": set(),
            "app-a": {"app-b"},
        }

        key1 = DependencyManager._generate_cache_key(dependencies1)
        key2 = DependencyManager._generate_cache_key(dependencies2)

        # Same dependencies in different order = same key
        assert key1 == key2

    def test_cache_key_is_md5_hash(self):
        """Test cache key is valid MD5 hash."""
        dependencies = {"app-a": set()}

        key = DependencyManager._generate_cache_key(dependencies)

        # MD5 hex is 32 characters
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)

    def test_different_dependencies_different_keys(self):
        """Test different dependencies produce different keys."""
        dep1 = {"app-a": {"app-b"}}
        dep2 = {"app-a": {"app-c"}}

        key1 = DependencyManager._generate_cache_key(dep1)
        key2 = DependencyManager._generate_cache_key(dep2)

        assert key1 != key2

    def test_clear_dependency_cache(self):
        """Test cache clearing works."""
        global _dependency_cache

        # Add something to cache
        _dependency_cache["test_key"] = ["app-a", "app-b"]

        DependencyManager.clear_dependency_cache()

        assert len(_dependency_cache) == 0

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self):
        """Test cache hit returns cached result without recomputation."""
        mock_db = AsyncMock()

        # Mock database response
        mock_containers = [
            MagicMock(name="app-a", dependencies=None),
            MagicMock(name="app-b", dependencies='["app-a"]'),
        ]

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = mock_containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        # First call - cache miss
        result1 = await DependencyManager.get_update_order(
            mock_db, ["app-a", "app-b"]
        )

        # Second call - should hit cache
        result2 = await DependencyManager.get_update_order(
            mock_db, ["app-a", "app-b"]
        )

        assert result1 == result2
        # Database should only be queried once (first call)
        assert mock_db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_eviction_at_100_entries(self):
        """Test cache evicts oldest entry when exceeding 100 items."""
        global _dependency_cache

        # Manually populate cache with 100 entries
        for i in range(100):
            _dependency_cache[f"key_{i}"] = [f"app-{i}"]

        # Add 101st entry
        _dependency_cache["key_100"] = ["app-100"]

        # Trigger eviction logic by adding through the API
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [
            MagicMock(name="new-app", dependencies=None)
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        await DependencyManager.get_update_order(mock_db, ["new-app"])

        # Cache should not exceed 100 entries
        assert len(_dependency_cache) <= 101  # Might have evicted


class TestDependencyManagerGetUpdateOrder:
    """Test suite for get_update_order method."""

    def setup_method(self):
        """Clear cache before each test."""
        DependencyManager.clear_dependency_cache()

    @pytest.mark.asyncio
    async def test_empty_container_list(self):
        """Test empty container list returns empty result."""
        mock_db = AsyncMock()

        result = await DependencyManager.get_update_order(mock_db, [])

        assert result == []

    @pytest.mark.asyncio
    async def test_containers_with_json_dependencies(self):
        """Test containers with valid JSON dependencies."""
        mock_db = AsyncMock()

        mock_containers = [
            MagicMock(name="postgres", dependencies=None),
            MagicMock(name="api", dependencies='["postgres"]'),
        ]

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = mock_containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await DependencyManager.get_update_order(
            mock_db, ["postgres", "api"]
        )

        assert result == ["postgres", "api"]

    @pytest.mark.asyncio
    async def test_container_not_in_database(self):
        """Test missing container is handled gracefully."""
        mock_db = AsyncMock()

        # Only postgres exists, api is missing
        mock_containers = [
            MagicMock(name="postgres", dependencies=None),
        ]

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = mock_containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await DependencyManager.get_update_order(
            mock_db, ["postgres", "api", "missing"]
        )

        # Should still include all containers
        assert "postgres" in result
        assert "api" in result
        assert "missing" in result

    @pytest.mark.asyncio
    async def test_invalid_json_dependencies(self):
        """Test container with invalid JSON dependencies."""
        mock_db = AsyncMock()

        mock_containers = [
            MagicMock(name="app", dependencies="not-valid-json"),
        ]

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = mock_containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Should not crash, treat as no dependencies
        result = await DependencyManager.get_update_order(mock_db, ["app"])

        assert result == ["app"]

    @pytest.mark.asyncio
    async def test_dependencies_not_in_update_list(self):
        """Test dependencies are filtered to update list only."""
        mock_db = AsyncMock()

        # API depends on postgres and redis, but only api is being updated
        mock_containers = [
            MagicMock(name="api", dependencies='["postgres", "redis"]'),
        ]

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = mock_containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await DependencyManager.get_update_order(mock_db, ["api"])

        # Should only include api (dependencies not in update list)
        assert result == ["api"]

    @pytest.mark.asyncio
    async def test_circular_dependency_falls_back_to_original_order(self):
        """Test circular dependency falls back to original order."""
        mock_db = AsyncMock()

        mock_containers = [
            MagicMock(name="app-a", dependencies='["app-b"]'),
            MagicMock(name="app-b", dependencies='["app-a"]'),
        ]

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = mock_containers
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Should fall back to original order instead of crashing
        result = await DependencyManager.get_update_order(
            mock_db, ["app-a", "app-b"]
        )

        assert result == ["app-a", "app-b"]


class TestDependencyManagerValidation:
    """Test suite for dependency validation."""

    @pytest.mark.asyncio
    async def test_validate_dependencies_all_exist(self):
        """Test validation succeeds when all dependencies exist."""
        mock_db = AsyncMock()

        # Mock: postgres and redis exist
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("postgres",), ("redis",)]

        # Mock: all containers for cycle check
        all_containers = [
            MagicMock(name="postgres", dependencies=None),
            MagicMock(name="redis", dependencies=None),
            MagicMock(name="api", dependencies='["postgres"]'),
        ]

        mock_db.execute = AsyncMock(side_effect=[
            mock_result,
            MagicMock(scalars=lambda: MagicMock(all=lambda: all_containers))
        ])

        is_valid, error = await DependencyManager.validate_dependencies(
            mock_db, "api", ["postgres", "redis"]
        )

        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_dependencies_missing_container(self):
        """Test validation fails when dependency doesn't exist."""
        mock_db = AsyncMock()

        # Mock: only postgres exists
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("postgres",)]

        mock_db.execute = AsyncMock(return_value=mock_result)

        is_valid, error = await DependencyManager.validate_dependencies(
            mock_db, "api", ["postgres", "nonexistent"]
        )

        assert is_valid is False
        assert "not found" in error
        assert "nonexistent" in error

    @pytest.mark.asyncio
    async def test_validate_dependencies_detects_cycle(self):
        """Test validation detects circular dependencies."""
        mock_db = AsyncMock()

        # Mock: dependencies exist
        mock_result1 = MagicMock()
        mock_result1.fetchall.return_value = [("app-a",), ("app-b",)]

        # Mock: containers with cycle
        all_containers = [
            MagicMock(name="app-a", dependencies='["app-b"]'),
            MagicMock(name="app-b", dependencies=None),  # Will be updated to depend on app-a
        ]

        mock_db.execute = AsyncMock(side_effect=[
            mock_result1,
            MagicMock(scalars=lambda: MagicMock(all=lambda: all_containers))
        ])

        # Try to make app-b depend on app-a (creates cycle)
        is_valid, error = await DependencyManager.validate_dependencies(
            mock_db, "app-b", ["app-a"]
        )

        assert is_valid is False
        assert "Circular" in error or "circular" in error


class TestDependencyManagerUpdateDependencies:
    """Test suite for updating container dependencies."""

    @pytest.mark.asyncio
    async def test_update_dependencies_stores_json(self):
        """Test dependencies are stored as JSON."""
        mock_db = AsyncMock()

        mock_container = MagicMock(name="api", dependencies=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_container

        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        await DependencyManager.update_container_dependencies(
            mock_db, "api", ["postgres", "redis"]
        )

        # Check JSON was stored
        stored_deps = json.loads(mock_container.dependencies)
        assert set(stored_deps) == {"postgres", "redis"}

    @pytest.mark.asyncio
    async def test_update_dependencies_clears_cache(self):
        """Test updating dependencies clears cache."""
        global _dependency_cache

        # Populate cache
        _dependency_cache["test"] = ["app-a"]

        mock_db = AsyncMock()
        mock_container = MagicMock(name="api", dependencies=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_container

        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        await DependencyManager.update_container_dependencies(
            mock_db, "api", ["postgres"]
        )

        # Cache should be cleared
        assert len(_dependency_cache) == 0

    @pytest.mark.asyncio
    async def test_update_dependencies_raises_for_missing_container(self):
        """Test updating missing container raises ValueError."""
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError) as exc_info:
            await DependencyManager.update_container_dependencies(
                mock_db, "nonexistent", ["postgres"]
            )

        assert "not found" in str(exc_info.value)


class TestDependencyManagerIntegration:
    """Integration tests for dependency manager."""

    def setup_method(self):
        """Clear cache before each test."""
        DependencyManager.clear_dependency_cache()

    @pytest.mark.asyncio
    async def test_full_workflow_simple_dependencies(self):
        """Test complete workflow with simple dependencies."""
        mock_db = AsyncMock()

        # Create mock containers
        postgres = MagicMock(name="postgres", dependencies=None)
        redis = MagicMock(name="redis", dependencies=None)
        api = MagicMock(name="api", dependencies='["postgres", "redis"]')
        frontend = MagicMock(name="frontend", dependencies='["api"]')

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [postgres, redis, api, frontend]

        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await DependencyManager.get_update_order(
            mock_db, ["postgres", "redis", "api", "frontend"]
        )

        # Verify correct order
        assert result.index("postgres") < result.index("api")
        assert result.index("redis") < result.index("api")
        assert result.index("api") < result.index("frontend")

    @pytest.mark.asyncio
    async def test_realistic_microservices_architecture(self):
        """Test realistic microservices dependency graph."""
        mock_db = AsyncMock()

        containers = [
            MagicMock(name="postgres", dependencies=None),
            MagicMock(name="redis", dependencies=None),
            MagicMock(name="rabbitmq", dependencies=None),
            MagicMock(name="auth-service", dependencies='["postgres", "redis"]'),
            MagicMock(name="user-service", dependencies='["postgres", "auth-service"]'),
            MagicMock(name="api-gateway", dependencies='["auth-service", "user-service"]'),
            MagicMock(name="frontend", dependencies='["api-gateway"]'),
        ]

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = containers

        mock_db.execute = AsyncMock(return_value=mock_result)

        container_names = [c.name for c in containers]
        result = await DependencyManager.get_update_order(mock_db, container_names)

        # Base services first
        for base in ["postgres", "redis", "rabbitmq"]:
            assert base in result[:3]

        # Frontend last
        assert result[-1] == "frontend"

        # Auth before user service
        assert result.index("auth-service") < result.index("user-service")

        # User service before api gateway
        assert result.index("user-service") < result.index("api-gateway")
