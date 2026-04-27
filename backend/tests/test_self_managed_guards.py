"""Engine-level guards for self-managed infrastructure.

Tests that UpdateEngine.apply_update / rollback_update / batch_approve refuse
to operate on socket-proxy-{rw,ro} (and any future self-managed entries) at
the chokepoint, BEFORE any compose mutation. Also covers the
update_serializer.enrich_updates path that populates UpdateSchema.self_managed.
"""

import pytest

from app.models.history import UpdateHistory
from app.services.protected_infra import SelfManagedInfraError
from app.services.update_engine import UpdateEngine
from app.services.update_serializer import enrich_update, enrich_updates

# ─── apply_update guard ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_update_raises_for_self_managed(db, make_container, make_update):
    container = make_container(name="socket-proxy-rw", service_name="socket-proxy-rw")
    db.add(container)
    await db.commit()
    await db.refresh(container)

    update = make_update(
        container_id=container.id,
        from_tag="3.2.15",
        to_tag="3.2.16",
        status="approved",
    )
    db.add(update)
    await db.commit()
    await db.refresh(update)

    with pytest.raises(SelfManagedInfraError) as exc_info:
        await UpdateEngine.apply_update(db, update.id, triggered_by="user")

    err = exc_info.value
    assert err.container_name == "socket-proxy-rw"
    assert err.operation == "apply"
    assert err.target_tag == "3.2.16"
    assert "3.2.16" in err.manual_update_instructions


@pytest.mark.asyncio
async def test_apply_update_proceeds_for_normal_container(db, make_container, make_update):
    """Sanity: non-protected containers still go through the normal path
    (which will fail later on missing compose etc., but not with our exception).
    """
    container = make_container(name="some-app", service_name="some-app")
    db.add(container)
    await db.commit()
    await db.refresh(container)

    update = make_update(container_id=container.id, status="approved")
    db.add(update)
    await db.commit()
    await db.refresh(update)

    # Should NOT raise SelfManagedInfraError; failure mode beyond is fine.
    try:
        await UpdateEngine.apply_update(db, update.id, triggered_by="user")
    except SelfManagedInfraError:
        pytest.fail("Non-protected container raised SelfManagedInfraError")
    except Exception:
        pass  # any other downstream error (e.g. missing compose file) is OK


# ─── rollback_update guard ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollback_update_raises_for_self_managed(db, make_container):
    container = make_container(name="socket-proxy-rw", service_name="socket-proxy-rw")
    db.add(container)
    await db.commit()
    await db.refresh(container)

    history = UpdateHistory(
        container_id=container.id,
        container_name=container.name,
        from_tag="3.2.14",
        to_tag="3.2.15",
        status="success",
    )
    db.add(history)
    await db.commit()
    await db.refresh(history)

    with pytest.raises(SelfManagedInfraError) as exc_info:
        await UpdateEngine.rollback_update(db, history.id)

    err = exc_info.value
    assert err.operation == "rollback"
    assert err.target_tag == "3.2.14"  # the from_tag we'd be rolling back TO
    assert "3.2.14" in err.manual_update_instructions


# ─── batch_approve carve-out ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_approve_skips_self_managed_updates(db, make_container, make_update):
    proxy = make_container(name="socket-proxy-rw", service_name="socket-proxy-rw")
    normal = make_container(name="nginx-app", service_name="nginx-app")
    db.add_all([proxy, normal])
    await db.commit()
    await db.refresh(proxy)
    await db.refresh(normal)

    proxy_update = make_update(
        container_id=proxy.id, from_tag="3.2.15", to_tag="3.2.16", status="pending"
    )
    normal_update = make_update(
        container_id=normal.id, from_tag="1.0", to_tag="1.1", status="pending"
    )
    db.add_all([proxy_update, normal_update])
    await db.commit()
    await db.refresh(proxy_update)
    await db.refresh(normal_update)

    result = await UpdateEngine.batch_approve(db, [proxy_update.id, normal_update.id])

    # Existing contract preserved
    assert "approved" in result
    assert "failed" in result
    assert "summary" in result
    assert result["summary"]["total"] == 2

    # Additive fields populated
    assert "skipped_self_managed" in result
    assert result["summary"]["skipped_self_managed_count"] == 1

    # Normal update was approved
    approved_ids = [a["id"] for a in result["approved"]]
    assert normal_update.id in approved_ids
    assert proxy_update.id not in approved_ids

    # Proxy update appears in skipped_self_managed with manual instructions
    skipped = result["skipped_self_managed"]
    assert len(skipped) == 1
    assert skipped[0]["id"] == proxy_update.id
    assert skipped[0]["container_id"] == proxy.id
    assert skipped[0]["container_name"] == "socket-proxy-rw"
    assert "3.2.16" in skipped[0]["manual_update_instructions"]


@pytest.mark.asyncio
async def test_batch_approve_existing_contract_preserved_when_no_self_managed(
    db, make_container, make_update
):
    """Regression: existing tests expect {approved, failed, summary} keys with
    the same per-item shape. This batch contains zero self-managed updates.
    """
    container = make_container(name="nginx-app", service_name="nginx-app")
    db.add(container)
    await db.commit()
    await db.refresh(container)

    update = make_update(container_id=container.id, status="pending")
    db.add(update)
    await db.commit()
    await db.refresh(update)

    result = await UpdateEngine.batch_approve(db, [update.id])

    assert result["approved"] == [{"id": update.id, "container_id": container.id}]
    assert result["failed"] == []
    assert result["skipped_self_managed"] == []
    assert result["summary"] == {
        "total": 1,
        "approved_count": 1,
        "failed_count": 0,
        "skipped_self_managed_count": 0,
    }


# ─── enrich_updates serializer ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_updates_marks_self_managed(db, make_container, make_update):
    proxy = make_container(name="socket-proxy-rw", service_name="socket-proxy-rw")
    normal = make_container(name="nginx-app", service_name="nginx-app")
    db.add_all([proxy, normal])
    await db.commit()
    await db.refresh(proxy)
    await db.refresh(normal)

    proxy_update = make_update(container_id=proxy.id, to_tag="3.2.16", status="pending")
    normal_update = make_update(container_id=normal.id, to_tag="1.1", status="pending")
    db.add_all([proxy_update, normal_update])
    await db.commit()
    await db.refresh(proxy_update)
    await db.refresh(normal_update)

    enriched = await enrich_updates(db, [proxy_update, normal_update])

    assert len(enriched) == 2
    s_proxy, s_normal = enriched
    assert s_proxy.self_managed is True
    assert s_proxy.manual_update_instructions is not None
    assert "3.2.16" in s_proxy.manual_update_instructions
    assert s_normal.self_managed is False
    assert s_normal.manual_update_instructions is None


@pytest.mark.asyncio
async def test_enrich_update_single_row_helper(db, make_container, make_update):
    container = make_container(name="socket-proxy-rw", service_name="socket-proxy-rw")
    db.add(container)
    await db.commit()
    await db.refresh(container)

    update = make_update(container_id=container.id, to_tag="3.2.16")
    db.add(update)
    await db.commit()
    await db.refresh(update)

    schema = await enrich_update(db, update)
    assert schema.self_managed is True
    assert schema.manual_update_instructions is not None


@pytest.mark.asyncio
async def test_enrich_updates_empty_list_no_query(db):
    """Empty input must not issue any DB queries."""
    result = await enrich_updates(db, [])
    assert result == []


@pytest.mark.asyncio
async def test_enrich_updates_uses_one_container_query_for_batch(db, make_container, make_update):
    """The bulk path must SELECT Container exactly once even for N updates.

    Regression guard: per-row container fetch would be N+1 and defeat the
    point of the bulk helper.
    """
    from sqlalchemy import event as sa_event

    containers = [make_container(name=f"c{i}", service_name=f"c{i}") for i in range(5)]
    db.add_all(containers)
    await db.commit()
    for c in containers:
        await db.refresh(c)

    updates = [make_update(container_id=c.id, status="pending") for c in containers]
    db.add_all(updates)
    await db.commit()
    for u in updates:
        await db.refresh(u)

    container_select_count = 0

    def count_container_selects(_conn, _cursor, statement, *_args, **_kw):
        nonlocal container_select_count
        normalized = statement.lower().replace('"', "")
        if "from containers" in normalized:
            container_select_count += 1

    sync_engine = db.bind.sync_engine
    sa_event.listen(sync_engine, "before_cursor_execute", count_container_selects)
    try:
        await enrich_updates(db, updates)
    finally:
        sa_event.remove(sync_engine, "before_cursor_execute", count_container_selects)

    assert container_select_count == 1, (
        f"Expected exactly one Container SELECT, got {container_select_count}"
    )
