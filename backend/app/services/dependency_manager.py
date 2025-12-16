"""Dependency manager for ordered container updates."""

import json
import logging
from typing import List, Dict, Set, Optional, Tuple
from functools import lru_cache
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.utils.security import sanitize_log_message

logger = logging.getLogger(__name__)


# Cache for dependency graph results (keyed by hash of dependencies)
_dependency_cache: Dict[str, List[str]] = {}


class DependencyManager:
    """Service for managing container dependencies and update ordering."""

    @staticmethod
    def _generate_cache_key(dependencies: Dict[str, Set[str]]) -> str:
        """Generate cache key from dependency graph.

        Args:
            dependencies: Dependency graph

        Returns:
            MD5 hash of the serialized graph
        """
        # Sort keys and convert sets to sorted lists for deterministic serialization
        normalized = {
            name: sorted(list(deps))
            for name, deps in sorted(dependencies.items())
        }
        serialized = json.dumps(normalized, sort_keys=True)
        return hashlib.md5(serialized.encode()).hexdigest()

    @staticmethod
    async def get_update_order(
        db: AsyncSession,
        container_names: List[str]
    ) -> List[str]:
        """Get containers in dependency-ordered update sequence with caching.

        Containers with no dependencies are updated first, followed by their
        dependents in topological order.

        Args:
            db: Database session
            container_names: List of container names to order

        Returns:
            List of container names in update order

        Raises:
            ValueError: If circular dependencies are detected
        """
        if not container_names:
            return []

        # Get all containers with their dependencies
        result = await db.execute(
            select(Container).where(Container.name.in_(container_names))
        )
        containers = {c.name: c for c in result.scalars().all()}

        # Build dependency graph
        dependencies: Dict[str, Set[str]] = {}

        for name in container_names:
            container = containers.get(name)
            if not container:
                logger.warning(f"Container {sanitize_log_message(str(name))} not found in database")
                dependencies[name] = set()
                continue

            # Parse dependencies from JSON string
            deps = set()
            if container.dependencies:
                try:
                    deps_list = json.loads(container.dependencies)
                    if isinstance(deps_list, list):
                        # Only include dependencies that are in the update list
                        deps = {
                            d for d in deps_list
                            if d in container_names
                        }
                except json.JSONDecodeError:
                    logger.warning(
                        f"Invalid dependencies JSON for {name}: "
                        f"{container.dependencies}"
                    )

            dependencies[name] = deps

        # Check cache first
        cache_key = DependencyManager._generate_cache_key(dependencies)
        if cache_key in _dependency_cache:
            logger.debug(f"Cache hit for dependency resolution ({sanitize_log_message(str(len(container_names)))} containers)")
            return _dependency_cache[cache_key]

        # Perform topological sort
        try:
            result_order = DependencyManager._topological_sort(dependencies)

            # Cache the result
            _dependency_cache[cache_key] = result_order
            logger.debug(f"Cached dependency resolution for {sanitize_log_message(str(len(container_names)))} containers")

            # Limit cache size to prevent memory issues (keep last 100 results)
            if len(_dependency_cache) > 100:
                # Remove oldest entry (first key)
                oldest_key = next(iter(_dependency_cache))
                del _dependency_cache[oldest_key]
                logger.debug("Evicted oldest dependency cache entry")

            return result_order
        except ValueError as e:
            logger.error(f"Dependency error: {sanitize_log_message(str(e))}")
            # Fall back to original order if there's a cycle
            logger.warning("Falling back to original order due to cycle")
            return container_names

    @staticmethod
    def _topological_sort(dependencies: Dict[str, Set[str]]) -> List[str]:
        """Perform topological sort on dependency graph.

        Uses Kahn's algorithm for cycle detection.

        Args:
            dependencies: Dict mapping container names to their dependencies

        Returns:
            List of container names in dependency order

        Raises:
            ValueError: If circular dependencies are detected
        """
        # Calculate in-degree (number of dependencies) for each node
        in_degree = {name: len(deps) for name, deps in dependencies.items()}

        # Find all nodes with no dependencies (in-degree = 0)
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        # Process nodes in dependency order
        while queue:
            # Sort queue for deterministic ordering
            queue.sort()

            # Process node with no dependencies
            current = queue.pop(0)
            result.append(current)

            # Update in-degree for dependents
            for name, deps in dependencies.items():
                if current in deps:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        # Check if all nodes were processed
        if len(result) != len(dependencies):
            # Circular dependency detected
            unprocessed = set(dependencies.keys()) - set(result)
            raise ValueError(
                f"Circular dependency detected involving: {', '.join(unprocessed)}"
            )

        return result

    @staticmethod
    async def auto_detect_dependencies(
        db: AsyncSession,
        container_name: str
    ) -> List[str]:
        """Auto-detect container dependencies from Docker compose links/depends_on.

        This is a placeholder for future implementation that would parse
        compose files to automatically detect dependencies.

        Args:
            db: Database session
            container_name: Container to analyze

        Returns:
            List of dependency container names
        """
        # TODO: Implement compose file parsing to detect:
        # - depends_on
        # - links
        # - network dependencies
        # For now, return empty list (manual configuration required)
        logger.debug(
            f"Auto-detect dependencies not yet implemented for {container_name}"
        )
        return []

    @staticmethod
    def clear_dependency_cache() -> None:
        """Clear the dependency resolution cache.

        Should be called when container dependencies are modified.
        """
        global _dependency_cache
        _dependency_cache.clear()
        logger.debug("Cleared dependency resolution cache")

    @staticmethod
    async def update_container_dependencies(
        db: AsyncSession,
        container_name: str,
        dependencies: List[str]
    ):
        """Update container dependencies and reverse-update dependents.

        Args:
            db: Database session
            container_name: Container to update
            dependencies: List of container names this container depends on
        """
        # Get the container
        result = await db.execute(
            select(Container).where(Container.name == container_name)
        )
        container = result.scalar_one_or_none()

        if not container:
            raise ValueError(f"Container {container_name} not found")

        # Store old dependencies to clean up reverse links
        old_deps = set()
        if container.dependencies:
            try:
                old_deps_list = json.loads(container.dependencies)
                if isinstance(old_deps_list, list):
                    old_deps = set(old_deps_list)
            except json.JSONDecodeError:
                pass

        new_deps = set(dependencies)

        # Update forward dependencies
        container.dependencies = json.dumps(list(new_deps))

        # Update reverse dependencies (dependents)
        # Remove this container from old dependencies' dependents lists
        for dep_name in old_deps - new_deps:
            await DependencyManager._remove_from_dependents(db, dep_name, container_name)

        # Add this container to new dependencies' dependents lists
        for dep_name in new_deps - old_deps:
            await DependencyManager._add_to_dependents(db, dep_name, container_name)

        # Clear cache since dependencies changed
        DependencyManager.clear_dependency_cache()

        await db.commit()
        logger.info(
            f"Updated dependencies for {container_name}: {dependencies}"
        )

    @staticmethod
    async def _add_to_dependents(
        db: AsyncSession,
        container_name: str,
        dependent_name: str
    ):
        """Add a dependent to a container's dependents list.

        Args:
            db: Database session
            container_name: Container that is depended on
            dependent_name: Container that depends on container_name
        """
        result = await db.execute(
            select(Container).where(Container.name == container_name)
        )
        container = result.scalar_one_or_none()

        if not container:
            logger.warning(
                f"Cannot add dependent {dependent_name} to non-existent "
                f"container {container_name}"
            )
            return

        # Parse current dependents
        dependents = set()
        if container.dependents:
            try:
                dependents_list = json.loads(container.dependents)
                if isinstance(dependents_list, list):
                    dependents = set(dependents_list)
            except json.JSONDecodeError:
                pass

        # Add new dependent
        dependents.add(dependent_name)
        container.dependents = json.dumps(list(dependents))

    @staticmethod
    async def _remove_from_dependents(
        db: AsyncSession,
        container_name: str,
        dependent_name: str
    ):
        """Remove a dependent from a container's dependents list.

        Args:
            db: Database session
            container_name: Container that is depended on
            dependent_name: Container to remove from dependents
        """
        result = await db.execute(
            select(Container).where(Container.name == container_name)
        )
        container = result.scalar_one_or_none()

        if not container:
            return

        # Parse current dependents
        dependents = set()
        if container.dependents:
            try:
                dependents_list = json.loads(container.dependents)
                if isinstance(dependents_list, list):
                    dependents = set(dependents_list)
            except json.JSONDecodeError:
                pass

        # Remove dependent
        dependents.discard(dependent_name)
        container.dependents = json.dumps(list(dependents))

    @staticmethod
    async def validate_dependencies(
        db: AsyncSession,
        container_name: str,
        dependencies: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """Validate that dependencies exist and won't create cycles.

        Args:
            db: Database session
            container_name: Container to validate
            dependencies: Proposed dependencies

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check that all dependencies exist
        result = await db.execute(
            select(Container.name).where(Container.name.in_(dependencies))
        )
        existing = {name for (name,) in result.fetchall()}

        missing = set(dependencies) - existing
        if missing:
            return False, f"Dependencies not found: {', '.join(missing)}"

        # Check for circular dependencies
        # Build temporary graph with proposed change
        result = await db.execute(select(Container))
        all_containers = result.scalars().all()

        dep_graph: Dict[str, Set[str]] = {}
        for container in all_containers:
            if container.name == container_name:
                # Use proposed dependencies
                dep_graph[container.name] = set(dependencies)
            else:
                # Use existing dependencies
                deps = set()
                if container.dependencies:
                    try:
                        deps_list = json.loads(container.dependencies)
                        if isinstance(deps_list, list):
                            deps = set(deps_list)
                    except json.JSONDecodeError:
                        pass
                dep_graph[container.name] = deps

        # Try topological sort to detect cycles
        try:
            DependencyManager._topological_sort(dep_graph)
            return True, None
        except ValueError as e:
            return False, str(e)
