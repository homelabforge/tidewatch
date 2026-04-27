"""Tests for self-managed indicator in NotificationDispatcher methods.

When a self-managed-infrastructure update is detected, the dispatcher must
include the manual command in the notification body (and adjust the title)
so the user can act on the Ntfy push without opening the UI.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.notifications.dispatcher import NotificationDispatcher


@pytest.fixture
def mock_dispatcher(db):
    """Build a dispatcher with `dispatch` mocked so we can inspect calls."""
    d = NotificationDispatcher(db)
    d.dispatch = AsyncMock(return_value={})
    return d


@pytest.mark.asyncio
async def test_notify_update_available_no_self_managed(mock_dispatcher):
    """Without manual_update_instructions, body and title are unchanged."""
    await mock_dispatcher.notify_update_available("nginx", "1.20", "1.21", "Standard release")
    args, kwargs = mock_dispatcher.dispatch.call_args
    assert kwargs["title"] == "Update Available: nginx"
    assert "Self-managed" not in kwargs["message"]


@pytest.mark.asyncio
async def test_notify_update_available_with_self_managed(mock_dispatcher):
    """When manual_update_instructions is passed, body includes them and title flips."""
    instructions = (
        "Edit compose file (/compose/proxies.yml) — set socket-proxy-rw image "
        "to version 3.2.16. Then run: dcp pull socket-proxy-rw && dcp up -d socket-proxy-rw"
    )
    await mock_dispatcher.notify_update_available(
        "socket-proxy-rw",
        "3.2.15",
        "3.2.16",
        "New version available",
        manual_update_instructions=instructions,
    )
    args, kwargs = mock_dispatcher.dispatch.call_args
    assert kwargs["title"] == "Manual Update Required: socket-proxy-rw"
    assert "Self-managed" in kwargs["message"]
    assert instructions in kwargs["message"]


@pytest.mark.asyncio
async def test_notify_security_update_no_self_managed(mock_dispatcher):
    await mock_dispatcher.notify_security_update("nginx", "1.20", "1.21", ["CVE-2025-1234"], -1)
    args, kwargs = mock_dispatcher.dispatch.call_args
    assert kwargs["title"] == "Security Update: nginx"
    assert "Self-managed" not in kwargs["message"]
    assert kwargs["priority"] == "high"


@pytest.mark.asyncio
async def test_notify_security_update_with_self_managed(mock_dispatcher):
    instructions = "Edit compose file — set X. Then run: dcp pull X && dcp up -d X"
    await mock_dispatcher.notify_security_update(
        "socket-proxy-rw",
        "3.2.15",
        "3.2.16",
        ["CVE-2025-1234"],
        -1,
        manual_update_instructions=instructions,
    )
    args, kwargs = mock_dispatcher.dispatch.call_args
    assert kwargs["title"] == "Manual Security Update Required: socket-proxy-rw"
    assert "Self-managed" in kwargs["message"]
    assert instructions in kwargs["message"]
    # CVE / security framing preserved
    assert "CVE-2025-1234" in kwargs["message"]
    assert kwargs["priority"] == "high"


@pytest.mark.asyncio
async def test_update_checker_passes_instructions_for_self_managed_container(
    db, make_container, make_update
):
    """End-to-end through update_checker.check_auto_approve_and_notify:
    a self-managed container gets a notification with manual_update_instructions.
    """
    from app.services.update_checker import UpdateChecker

    proxy = make_container(name="socket-proxy-rw", service_name="socket-proxy-rw")
    db.add(proxy)
    await db.commit()
    await db.refresh(proxy)

    update = make_update(
        container_id=proxy.id,
        container_name=proxy.name,
        from_tag="3.2.15",
        to_tag="3.2.16",
        status="pending",
        reason_type="update",
    )
    db.add(update)
    await db.commit()
    await db.refresh(update)

    captured: dict = {}

    async def fake_notify(
        container_name, from_tag, to_tag, reason, manual_update_instructions=None
    ):
        captured["container_name"] = container_name
        captured["manual_update_instructions"] = manual_update_instructions
        return {}

    mock_dispatcher = AsyncMock()
    mock_dispatcher.notify_update_available = fake_notify

    with (
        patch(
            "app.services.notifications.dispatcher.NotificationDispatcher",
            return_value=mock_dispatcher,
        ),
        patch(
            "app.services.update_checker.SettingsService.get_bool",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        await UpdateChecker._process_auto_approval_and_notify(db, update, proxy)

    assert captured["container_name"] == "socket-proxy-rw"
    assert captured["manual_update_instructions"] is not None
    assert "3.2.16" in captured["manual_update_instructions"]
    assert "Edit compose file" in captured["manual_update_instructions"]
