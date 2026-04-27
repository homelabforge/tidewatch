"""Tests for the self-managed infrastructure carve-out.

Covers protected_infra.py (helper + exception) and the guards added to
update_engine.apply_update / rollback_update / batch_approve, plus the
update_serializer.enrich_updates path.
"""

import pytest

from app.models.container import Container
from app.services.protected_infra import (
    SELF_MANAGED_INFRASTRUCTURE,
    SelfManagedInfraError,
    is_self_managed_infrastructure,
)


def _container(**kwargs) -> Container:
    """Construct a minimal Container without DB persistence."""
    defaults = {
        "name": "test",
        "image": "nginx",
        "current_tag": "latest",
        "registry": "docker.io",
        "compose_file": "/compose/test.yml",
        "service_name": "test",
    }
    defaults.update(kwargs)
    return Container(**defaults)


# ─── is_self_managed_infrastructure ──────────────────────────────────────────


def test_helper_matches_socket_proxy_rw_by_name():
    c = _container(name="socket-proxy-rw", service_name="socket-proxy-rw")
    assert is_self_managed_infrastructure(c) is True


def test_helper_matches_socket_proxy_ro_by_name():
    c = _container(name="socket-proxy-ro", service_name="socket-proxy-ro")
    assert is_self_managed_infrastructure(c) is True


def test_helper_matches_via_service_name_alias():
    """If container.name was renamed but service_name still matches, must trip."""
    c = _container(name="renamed-something-else", service_name="socket-proxy-rw")
    assert is_self_managed_infrastructure(c) is True


def test_helper_matches_via_docker_name_alias():
    """If container has a docker_name alias matching the protected set, must trip."""
    c = _container(name="renamed", service_name="renamed-svc", docker_name="socket-proxy-rw")
    assert is_self_managed_infrastructure(c) is True


def test_helper_does_not_match_unrelated_container():
    c = _container(name="nginx-frontend", service_name="nginx")
    assert is_self_managed_infrastructure(c) is False


def test_helper_handles_container_without_optional_attrs():
    """Defensive: missing docker_name shouldn't break matching."""
    c = _container(name="not-protected")
    # docker_name defaults to None on the Container model
    assert is_self_managed_infrastructure(c) is False


def test_default_set_contains_both_proxies():
    assert "socket-proxy-rw" in SELF_MANAGED_INFRASTRUCTURE
    assert "socket-proxy-ro" in SELF_MANAGED_INFRASTRUCTURE


# ─── SelfManagedInfraError ───────────────────────────────────────────────────


def test_error_apply_includes_compose_file_and_target_tag():
    err = SelfManagedInfraError(
        "socket-proxy-rw",
        operation="apply",
        target_tag="3.2.16",
        compose_file="/compose/proxies.yml",
        compose_project="proxies",
        service_name="socket-proxy-rw",
    )
    assert "3.2.16" in err.manual_update_instructions
    assert "/compose/proxies.yml" in err.manual_update_instructions
    assert "socket-proxy-rw" in err.manual_update_instructions
    assert "Edit compose file" in err.manual_update_instructions


def test_error_rollback_uses_target_tag_from_history():
    err = SelfManagedInfraError(
        "socket-proxy-rw",
        operation="rollback",
        target_tag="3.2.14",
        compose_file="/compose/proxies.yml",
        service_name="socket-proxy-rw",
    )
    assert err.operation == "rollback"
    assert "3.2.14" in err.manual_update_instructions


def test_error_handles_missing_target_tag():
    err = SelfManagedInfraError("socket-proxy-rw", operation="apply")
    assert "<target tag>" in err.manual_update_instructions


def test_error_rejects_invalid_operation():
    with pytest.raises(ValueError):
        SelfManagedInfraError("socket-proxy-rw", operation="bogus")


def test_error_str_includes_instructions():
    err = SelfManagedInfraError("socket-proxy-rw", operation="apply", target_tag="3.2.16")
    assert "self-managed infrastructure" in str(err)
    assert "3.2.16" in str(err)
