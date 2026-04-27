"""Self-managed infrastructure containers — TideWatch must NOT auto-manage these.

These containers are part of TideWatch's own Docker API pathway. Updating them
through the normal apply/rollback flow would sever TideWatch's connection to
the Docker daemon mid-operation, leaving the container offline and the update
stuck. Approve/apply/rollback for these containers is blocked at the engine
level and surfaced to the user as a 409 with manual instructions.

The compose file is rewritten to update.to_tag BEFORE pull (see
update_engine.py apply path), so manual instructions MUST include the compose
edit step or `dcp pull && dcp up -d` would re-pull the OLD pinned tag.
"""

from app.models.container import Container

SELF_MANAGED_INFRASTRUCTURE: frozenset[str] = frozenset(
    {
        "socket-proxy-rw",
        "socket-proxy-ro",
    }
)


def is_self_managed_infrastructure(container: Container) -> bool:
    """Return True if this container is part of TideWatch's own infrastructure.

    Matches container.name, service_name, OR docker_name to be robust against
    network aliases. Name-only matching would silently fail if a future rename
    only updated one of those identifiers.
    """
    candidates = {
        getattr(container, "name", None),
        getattr(container, "service_name", None),
        getattr(container, "docker_name", None),
    }
    return bool(candidates & SELF_MANAGED_INFRASTRUCTURE)


class SelfManagedInfraError(Exception):
    """Raised when an apply/rollback/approve targets self-managed infrastructure.

    Manual instructions differ by operation:
    - apply/approve: bump compose file to update.to_tag, then pull/up
    - rollback: bump compose file to history.from_tag, then pull/up

    The compose file path, service name, and target tag are surfaced as
    structured fields so the UI can render copyable values (and a future
    "open compose in editor" button has structured data to work with).
    """

    OPERATIONS = ("apply", "rollback", "approve")

    def __init__(
        self,
        container_name: str,
        *,
        operation: str = "apply",
        target_tag: str | None = None,
        compose_file: str | None = None,
        compose_project: str | None = None,
        service_name: str | None = None,
    ) -> None:
        if operation not in self.OPERATIONS:
            raise ValueError(f"operation must be one of {self.OPERATIONS}")
        self.container_name = container_name
        self.operation = operation
        self.target_tag = target_tag
        self.compose_file = compose_file
        self.compose_project = compose_project
        self.service_name = service_name or container_name
        self.manual_update_instructions = self._build_instructions()
        super().__init__(
            f"{container_name} is self-managed infrastructure ({operation}). "
            f"{self.manual_update_instructions}"
        )

    def _build_instructions(self) -> str:
        file_hint = f" ({self.compose_file})" if self.compose_file else ""
        tag = self.target_tag or "<target tag>"
        return (
            f"Edit compose file{file_hint} — set {self.service_name} image to "
            f"version {tag}. Then run: dcp pull {self.service_name} && "
            f"dcp up -d {self.service_name}"
        )
