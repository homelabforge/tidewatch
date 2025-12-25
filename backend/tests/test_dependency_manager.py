"""Tests for dependency manager (app/services/dependency_manager.py).

Tests container dependency management and update ordering:
- Topological sort for dependency ordering
- Circular dependency detection
- Dependency graph caching
- Update order calculation
- Dependency validation
- Forward/reverse dependency management
- Cache eviction and clearing
"""

import pytest
import json
from unittest.mock import patch

from app.services.dependency_manager import DependencyManager


class TestGetUpdateOrder:
    """Test suite for get_update_order() method."""

    async def test_returns_empty_for_empty_list(self, db):
        """Test returns empty list for empty input."""
        result = await DependencyManager.get_update_order(db, [])
        assert result == []

    async def test_orders_independent_containers_alphabetically(
        self, db, make_container
    ):
        """Test orders independent containers alphabetically."""
        # Create containers with no dependencies
        container1 = make_container(name="web", image="nginx", current_tag="latest")
        container2 = make_container(name="api", image="node", current_tag="18")
        container3 = make_container(name="cache", image="redis", current_tag="7")
        db.add_all([container1, container2, container3])
        await db.commit()

        result = await DependencyManager.get_update_order(db, ["web", "api", "cache"])

        # Independent containers should be sorted alphabetically
        assert result == ["api", "cache", "web"]

    async def test_orders_linear_dependency_chain(self, db, make_container):
        """Test orders containers with linear dependency chain."""
        # db -> api -> web (web depends on api, api depends on db)
        db_container = make_container(
            name="db", image="postgres", current_tag="16", dependencies=None
        )
        api_container = make_container(
            name="api", image="node", current_tag="18", dependencies=json.dumps(["db"])
        )
        web_container = make_container(
            name="web",
            image="nginx",
            current_tag="latest",
            dependencies=json.dumps(["api"]),
        )
        db.add_all([db_container, api_container, web_container])
        await db.commit()

        result = await DependencyManager.get_update_order(db, ["web", "api", "db"])

        # Should order: db -> api -> web
        assert result == ["db", "api", "web"]

    async def test_orders_complex_dependency_tree(self, db, make_container):
        """Test orders containers with complex dependency tree."""
        # Dependency graph:
        #   db (no deps)
        #   cache (no deps)
        #   api (depends on db)
        #   worker (depends on db, cache)
        #   web (depends on api, cache)

        db_container = make_container(name="db", image="postgres", current_tag="16")
        cache_container = make_container(name="cache", image="redis", current_tag="7")
        api_container = make_container(
            name="api", image="node", current_tag="18", dependencies=json.dumps(["db"])
        )
        worker_container = make_container(
            name="worker",
            image="python",
            current_tag="3.11",
            dependencies=json.dumps(["db", "cache"]),
        )
        web_container = make_container(
            name="web",
            image="nginx",
            current_tag="latest",
            dependencies=json.dumps(["api", "cache"]),
        )

        db.add_all(
            [
                db_container,
                cache_container,
                api_container,
                worker_container,
                web_container,
            ]
        )
        await db.commit()

        result = await DependencyManager.get_update_order(
            db, ["web", "worker", "api", "cache", "db"]
        )

        # Verify ordering constraints
        db_idx = result.index("db")
        cache_idx = result.index("cache")
        api_idx = result.index("api")
        worker_idx = result.index("worker")
        web_idx = result.index("web")

        # db and cache must come before their dependents
        assert db_idx < api_idx
        assert db_idx < worker_idx
        assert cache_idx < worker_idx
        assert cache_idx < web_idx

        # api must come before web
        assert api_idx < web_idx

    async def test_ignores_external_dependencies(self, db, make_container):
        """Test ignores dependencies not in update list."""
        # web depends on api and external, but external is not in update list
        api_container = make_container(name="api", image="node", current_tag="18")
        web_container = make_container(
            name="web",
            image="nginx",
            current_tag="latest",
            dependencies=json.dumps(["api", "external-service"]),
        )
        db.add_all([api_container, web_container])
        await db.commit()

        result = await DependencyManager.get_update_order(db, ["web", "api"])

        # Should only consider api dependency
        assert result == ["api", "web"]

    async def test_handles_missing_containers(self, db, make_container):
        """Test handles containers not found in database."""
        container = make_container(name="web", image="nginx", current_tag="latest")
        db.add(container)
        await db.commit()

        result = await DependencyManager.get_update_order(db, ["web", "nonexistent"])

        # Should include all requested containers
        assert "web" in result
        assert "nonexistent" in result

    async def test_uses_cache_for_repeated_calls(self, db, make_container):
        """Test uses cache for repeated dependency resolution."""
        container1 = make_container(name="db", image="postgres", current_tag="16")
        container2 = make_container(
            name="api", image="node", current_tag="18", dependencies=json.dumps(["db"])
        )
        db.add_all([container1, container2])
        await db.commit()

        # Clear cache first
        DependencyManager.clear_dependency_cache()

        # First call
        result1 = await DependencyManager.get_update_order(db, ["api", "db"])

        # Second call with same dependencies
        with patch.object(DependencyManager, "_topological_sort") as mock_sort:
            result2 = await DependencyManager.get_update_order(db, ["api", "db"])

            # Should not call topological_sort (cache hit)
            mock_sort.assert_not_called()

        assert result1 == result2

    async def test_evicts_oldest_cache_entry(self, db, make_container):
        """Test evicts oldest cache entry when cache is full."""
        # Create many containers to fill cache beyond 100 entries
        DependencyManager.clear_dependency_cache()

        # Create 102 containers to ensure we can have 101 unique patterns
        containers = [
            make_container(name=f"container{i}", image="alpine", current_tag="3")
            for i in range(102)
        ]
        db.add_all(containers)
        await db.commit()

        # Fill cache with 101 different dependency patterns
        for i in range(101):
            # Create unique dependency pattern each time by including different container sets
            names = [
                f"container{j}" for j in range(i, i + 1)
            ]  # Each pattern has exactly 1 container, different each time
            await DependencyManager.get_update_order(db, names)

        # Cache should be limited to 100 entries
        from app.services.dependency_manager import _dependency_cache

        assert len(_dependency_cache) == 100

    async def test_falls_back_to_original_order_on_cycle(self, db, make_container):
        """Test falls back to original order if circular dependency detected."""
        # Create circular dependency: a -> b -> c -> a
        container_a = make_container(
            name="a", image="alpine", current_tag="3", dependencies=json.dumps(["c"])
        )
        container_b = make_container(
            name="b", image="busybox", current_tag="1", dependencies=json.dumps(["a"])
        )
        container_c = make_container(
            name="c", image="caddy", current_tag="2", dependencies=json.dumps(["b"])
        )
        db.add_all([container_a, container_b, container_c])
        await db.commit()

        result = await DependencyManager.get_update_order(db, ["a", "b", "c"])

        # Should fall back to original order
        assert result == ["a", "b", "c"]

    async def test_handles_invalid_json_dependencies(self, db, make_container, caplog):
        """Test handles invalid JSON in dependencies field."""
        container1 = make_container(name="db", image="postgres", current_tag="16")
        container2 = make_container(
            name="api", image="node", current_tag="18", dependencies="not-valid-json"
        )
        db.add_all([container1, container2])
        await db.commit()

        result = await DependencyManager.get_update_order(db, ["api", "db"])

        # Should treat api as having no dependencies
        assert result == ["api", "db"] or result == ["db", "api"]

        # Should log warning
        assert "Invalid dependencies JSON" in caplog.text


class TestTopologicalSort:
    """Test suite for _topological_sort() method."""

    def test_sorts_simple_graph(self):
        """Test sorts simple dependency graph."""
        dependencies = {"a": set(), "b": {"a"}, "c": {"b"}}

        result = DependencyManager._topological_sort(dependencies)

        assert result == ["a", "b", "c"]

    def test_sorts_graph_with_multiple_roots(self):
        """Test sorts graph with multiple independent roots."""
        dependencies = {"a": set(), "b": set(), "c": {"a", "b"}}

        result = DependencyManager._topological_sort(dependencies)

        # a and b should come before c (alphabetically ordered)
        assert result[:2] == ["a", "b"]
        assert result[2] == "c"

    def test_sorts_diamond_dependency(self):
        """Test sorts diamond-shaped dependency."""
        # d depends on b and c, both b and c depend on a
        dependencies = {"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}}

        result = DependencyManager._topological_sort(dependencies)

        # a must be first
        assert result[0] == "a"
        # b and c must come before d
        assert result.index("b") < result.index("d")
        assert result.index("c") < result.index("d")

    def test_raises_on_circular_dependency(self):
        """Test raises ValueError on circular dependency."""
        dependencies = {"a": {"b"}, "b": {"c"}, "c": {"a"}}

        with pytest.raises(ValueError, match="Circular dependency detected"):
            DependencyManager._topological_sort(dependencies)

    def test_raises_on_self_dependency(self):
        """Test raises ValueError on self dependency."""
        dependencies = {"a": {"a"}}

        with pytest.raises(ValueError, match="Circular dependency detected"):
            DependencyManager._topological_sort(dependencies)

    def test_handles_empty_graph(self):
        """Test handles empty dependency graph."""
        dependencies = {}

        result = DependencyManager._topological_sort(dependencies)

        assert result == []

    def test_handles_single_node(self):
        """Test handles single node with no dependencies."""
        dependencies = {"a": set()}

        result = DependencyManager._topological_sort(dependencies)

        assert result == ["a"]

    def test_deterministic_ordering(self):
        """Test produces deterministic ordering."""
        dependencies = {"z": set(), "y": set(), "x": set(), "w": {"x", "y", "z"}}

        # Run multiple times
        result1 = DependencyManager._topological_sort(dependencies)
        result2 = DependencyManager._topological_sort(dependencies)
        result3 = DependencyManager._topological_sort(dependencies)

        # Should always produce same result
        assert result1 == result2 == result3


class TestGenerateCacheKey:
    """Test suite for _generate_cache_key() method."""

    def test_generates_consistent_key_for_same_graph(self):
        """Test generates consistent key for same dependency graph."""
        dependencies = {"a": {"b"}, "b": {"c"}, "c": set()}

        key1 = DependencyManager._generate_cache_key(dependencies)
        key2 = DependencyManager._generate_cache_key(dependencies)

        assert key1 == key2

    def test_generates_same_key_for_different_order(self):
        """Test generates same key regardless of dict order."""
        dependencies1 = {"a": {"b"}, "c": set(), "b": {"c"}}

        dependencies2 = {"c": set(), "b": {"c"}, "a": {"b"}}

        key1 = DependencyManager._generate_cache_key(dependencies1)
        key2 = DependencyManager._generate_cache_key(dependencies2)

        # Should be same despite different insertion order
        assert key1 == key2

    def test_generates_different_key_for_different_graph(self):
        """Test generates different key for different graphs."""
        dependencies1 = {"a": {"b"}, "b": set()}

        dependencies2 = {"a": {"c"}, "c": set()}

        key1 = DependencyManager._generate_cache_key(dependencies1)
        key2 = DependencyManager._generate_cache_key(dependencies2)

        assert key1 != key2

    def test_generates_different_key_for_different_sets(self):
        """Test generates different key for different dependency sets."""
        dependencies1 = {"a": {"b", "c"}}

        dependencies2 = {"a": {"b"}}

        key1 = DependencyManager._generate_cache_key(dependencies1)
        key2 = DependencyManager._generate_cache_key(dependencies2)

        assert key1 != key2


class TestUpdateContainerDependencies:
    """Test suite for update_container_dependencies() method."""

    async def test_updates_container_dependencies(self, db, make_container):
        """Test updates container dependencies."""
        container_a = make_container(name="a", image="alpine", current_tag="3")
        container_b = make_container(name="b", image="busybox", current_tag="1")
        db.add_all([container_a, container_b])
        await db.commit()

        await DependencyManager.update_container_dependencies(db, "a", ["b"])

        # Refresh and check
        await db.refresh(container_a)
        deps = json.loads(container_a.dependencies)
        assert deps == ["b"]

    async def test_updates_reverse_dependencies(self, db, make_container):
        """Test updates reverse dependencies (dependents)."""
        container_a = make_container(name="a", image="alpine", current_tag="3")
        container_b = make_container(name="b", image="busybox", current_tag="1")
        db.add_all([container_a, container_b])
        await db.commit()

        await DependencyManager.update_container_dependencies(db, "a", ["b"])

        # Check reverse dependency
        await db.refresh(container_b)
        dependents = (
            json.loads(container_b.dependents) if container_b.dependents else []
        )
        assert "a" in dependents

    async def test_removes_old_dependencies(self, db, make_container):
        """Test removes old dependencies when updated."""
        container_a = make_container(
            name="a", image="alpine", current_tag="3", dependencies=json.dumps(["b"])
        )
        container_b = make_container(
            name="b", image="busybox", current_tag="1", dependents=json.dumps(["a"])
        )
        container_c = make_container(name="c", image="caddy", current_tag="2")
        db.add_all([container_a, container_b, container_c])
        await db.commit()

        # Update a to depend on c instead of b
        await DependencyManager.update_container_dependencies(db, "a", ["c"])

        # Check b no longer has a as dependent
        await db.refresh(container_b)
        dependents = (
            json.loads(container_b.dependents) if container_b.dependents else []
        )
        assert "a" not in dependents

        # Check c has a as dependent
        await db.refresh(container_c)
        dependents = (
            json.loads(container_c.dependents) if container_c.dependents else []
        )
        assert "a" in dependents

    async def test_clears_dependency_cache(self, db, make_container):
        """Test clears dependency cache when updated."""
        container = make_container(name="a", image="alpine", current_tag="3")
        db.add(container)
        await db.commit()

        # Fill cache
        await DependencyManager.get_update_order(db, ["a"])

        with patch.object(DependencyManager, "clear_dependency_cache") as mock_clear:
            await DependencyManager.update_container_dependencies(db, "a", [])
            mock_clear.assert_called_once()

    async def test_raises_on_container_not_found(self, db):
        """Test raises ValueError if container not found."""
        with pytest.raises(ValueError, match="Container nonexistent not found"):
            await DependencyManager.update_container_dependencies(db, "nonexistent", [])

    async def test_handles_invalid_json_in_old_dependencies(self, db, make_container):
        """Test handles invalid JSON in existing dependencies."""
        container = make_container(
            name="a", image="alpine", current_tag="3", dependencies="invalid-json"
        )
        db.add(container)
        await db.commit()

        # Should not raise
        await DependencyManager.update_container_dependencies(db, "a", ["b"])

    async def test_handles_missing_dependent_container(
        self, db, make_container, caplog
    ):
        """Test handles missing container when updating dependents."""
        container_a = make_container(name="a", image="alpine", current_tag="3")
        db.add(container_a)
        await db.commit()

        # Update to depend on non-existent container
        # (should be caught by validation, but test robustness)
        await DependencyManager._add_to_dependents(db, "nonexistent", "a")

        # Should log warning
        assert (
            "Cannot add dependent a to non-existent container nonexistent"
            in caplog.text
        )


class TestValidateDependencies:
    """Test suite for validate_dependencies() method."""

    async def test_validates_existing_dependencies(self, db, make_container):
        """Test validates that all dependencies exist."""
        container_a = make_container(name="a", image="alpine", current_tag="3")
        container_b = make_container(name="b", image="busybox", current_tag="1")
        db.add_all([container_a, container_b])
        await db.commit()

        is_valid, error = await DependencyManager.validate_dependencies(db, "a", ["b"])

        assert is_valid is True
        assert error is None

    async def test_rejects_missing_dependencies(self, db, make_container):
        """Test rejects dependencies that don't exist."""
        container_a = make_container(name="a", image="alpine", current_tag="3")
        db.add(container_a)
        await db.commit()

        is_valid, error = await DependencyManager.validate_dependencies(
            db, "a", ["nonexistent"]
        )

        assert is_valid is False
        assert "Dependencies not found: nonexistent" in error

    async def test_rejects_circular_dependencies(self, db, make_container):
        """Test rejects dependencies that create cycles."""
        # Create: a -> b -> c
        container_a = make_container(
            name="a", image="alpine", current_tag="3", dependencies=json.dumps(["b"])
        )
        container_b = make_container(
            name="b", image="busybox", current_tag="1", dependencies=json.dumps(["c"])
        )
        container_c = make_container(name="c", image="caddy", current_tag="2")
        db.add_all([container_a, container_b, container_c])
        await db.commit()

        # Try to make c -> a (creates cycle)
        is_valid, error = await DependencyManager.validate_dependencies(db, "c", ["a"])

        assert is_valid is False
        assert "Circular dependency detected" in error

    async def test_allows_complex_valid_graph(self, db, make_container):
        """Test allows complex but valid dependency graph."""
        container_a = make_container(name="a", image="alpine", current_tag="3")
        container_b = make_container(name="b", image="busybox", current_tag="1")
        container_c = make_container(
            name="c", image="caddy", current_tag="2", dependencies=json.dumps(["a"])
        )
        container_d = make_container(
            name="d", image="debian", current_tag="12", dependencies=json.dumps(["b"])
        )
        db.add_all([container_a, container_b, container_c, container_d])
        await db.commit()

        # Add e that depends on both c and d (diamond pattern)
        is_valid, error = await DependencyManager.validate_dependencies(
            db, "e", ["c", "d"]
        )

        assert is_valid is True
        assert error is None

    async def test_handles_empty_dependencies(self, db, make_container):
        """Test handles empty dependency list."""
        container = make_container(name="a", image="alpine", current_tag="3")
        db.add(container)
        await db.commit()

        is_valid, error = await DependencyManager.validate_dependencies(db, "a", [])

        assert is_valid is True
        assert error is None

    async def test_handles_invalid_json_in_existing_deps(self, db, make_container):
        """Test handles invalid JSON in existing container dependencies."""
        container_a = make_container(
            name="a", image="alpine", current_tag="3", dependencies="invalid"
        )
        container_b = make_container(name="b", image="busybox", current_tag="1")
        db.add_all([container_a, container_b])
        await db.commit()

        is_valid, error = await DependencyManager.validate_dependencies(db, "b", ["a"])

        # Should still validate successfully
        assert is_valid is True


class TestClearDependencyCache:
    """Test suite for clear_dependency_cache() method."""

    def test_clears_cache(self):
        """Test clears the dependency cache."""
        from app.services.dependency_manager import _dependency_cache

        # Add some entries
        _dependency_cache["key1"] = ["a", "b"]
        _dependency_cache["key2"] = ["c", "d"]

        DependencyManager.clear_dependency_cache()

        assert len(_dependency_cache) == 0

    def test_handles_empty_cache(self):
        """Test handles clearing empty cache."""
        DependencyManager.clear_dependency_cache()

        # Should not raise
        from app.services.dependency_manager import _dependency_cache

        assert len(_dependency_cache) == 0


class TestAutoDetectDependencies:
    """Test suite for auto_detect_dependencies() method."""

    async def test_returns_empty_list_placeholder(self, db):
        """Test returns empty list (placeholder implementation)."""
        result = await DependencyManager.auto_detect_dependencies(db, "test")

        assert result == []

    async def test_logs_not_implemented_message(self, db, caplog):
        """Test logs message about not implemented."""
        import logging

        caplog.set_level(logging.DEBUG)

        await DependencyManager.auto_detect_dependencies(db, "test")

        assert "Auto-detect dependencies not yet implemented" in caplog.text


class TestDependencyManagerEdgeCases:
    """Test edge cases and real-world scenarios."""

    async def test_handles_very_large_dependency_graph(self, db, make_container):
        """Test handles large dependency graph."""
        # Create 50 containers with various dependencies
        containers = []
        for i in range(50):
            deps = []
            if i > 0:
                # Each container depends on previous one
                deps = [f"container{i - 1}"]

            container = make_container(
                name=f"container{i}",
                image="test",
                current_tag="latest",
                dependencies=json.dumps(deps) if deps else None,
            )
            containers.append(container)

        db.add_all(containers)
        await db.commit()

        names = [f"container{i}" for i in range(50)]
        result = await DependencyManager.get_update_order(db, names)

        # Should be in order 0, 1, 2, ..., 49
        expected = [f"container{i}" for i in range(50)]
        assert result == expected

    async def test_handles_multiple_dependency_layers(self, db, make_container):
        """Test handles multiple layers of dependencies."""
        # Layer 0: db, cache
        # Layer 1: api (db), queue (cache)
        # Layer 2: worker (api, queue)
        # Layer 3: web (worker)

        layer0 = [
            make_container(name="db", image="postgres", current_tag="16"),
            make_container(name="cache", image="redis", current_tag="7"),
        ]
        layer1 = [
            make_container(
                name="api",
                image="node",
                current_tag="18",
                dependencies=json.dumps(["db"]),
            ),
            make_container(
                name="queue",
                image="rabbitmq",
                current_tag="3",
                dependencies=json.dumps(["cache"]),
            ),
        ]
        layer2 = [
            make_container(
                name="worker",
                image="python",
                current_tag="3.11",
                dependencies=json.dumps(["api", "queue"]),
            )
        ]
        layer3 = [
            make_container(
                name="web",
                image="nginx",
                current_tag="latest",
                dependencies=json.dumps(["worker"]),
            )
        ]

        db.add_all(layer0 + layer1 + layer2 + layer3)
        await db.commit()

        result = await DependencyManager.get_update_order(
            db, ["web", "worker", "api", "queue", "db", "cache"]
        )

        # Verify layer ordering
        db_idx = result.index("db")
        cache_idx = result.index("cache")
        api_idx = result.index("api")
        queue_idx = result.index("queue")
        worker_idx = result.index("worker")
        web_idx = result.index("web")

        # Layer 0 before layer 1
        assert db_idx < api_idx
        assert cache_idx < queue_idx

        # Layer 1 before layer 2
        assert api_idx < worker_idx
        assert queue_idx < worker_idx

        # Layer 2 before layer 3
        assert worker_idx < web_idx

    async def test_partial_update_with_dependencies(self, db, make_container):
        """Test updating subset of containers with dependencies."""
        # Full graph: a -> b -> c -> d
        # Only update b and c

        container_a = make_container(name="a", image="alpine", current_tag="3")
        container_b = make_container(
            name="b", image="busybox", current_tag="1", dependencies=json.dumps(["a"])
        )
        container_c = make_container(
            name="c", image="caddy", current_tag="2", dependencies=json.dumps(["b"])
        )
        container_d = make_container(
            name="d", image="debian", current_tag="12", dependencies=json.dumps(["c"])
        )

        db.add_all([container_a, container_b, container_c, container_d])
        await db.commit()

        result = await DependencyManager.get_update_order(db, ["c", "b"])

        # Should order b before c, ignoring a and d
        assert result == ["b", "c"]
