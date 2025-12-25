"""Debug test to see what's happening with filtering."""

import pytest
from app.models.container import Container


@pytest.mark.asyncio
async def test_filter_debug(authenticated_client, db):
    """Debug test to see what's returned."""
    # Create containers with different policies
    container1 = Container(
        name="debug-auto-1",
        image="nginx:1.20",
        current_tag="1.20",
        registry="docker.io",
        compose_file="/compose/test.yml",
        service_name="nginx",
        policy="auto",
    )
    container2 = Container(
        name="debug-manual-2",
        image="redis:6",
        current_tag="6",
        registry="docker.io",
        compose_file="/compose/test.yml",
        service_name="redis",
        policy="manual",
    )
    db.add_all([container1, container2])
    await db.commit()

    # Get all containers first
    response = await authenticated_client.get("/api/v1/containers/")
    print("\n=== ALL CONTAINERS ===")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Count: {len(data)}")
    for c in data:
        print(f"  - {c['name']}: policy={c['policy']}")

    # Filter by policy=auto
    response = await authenticated_client.get("/api/v1/containers/?policy=auto")
    print("\n=== FILTERED BY POLICY=auto ===")
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Count: {len(data)}")
    for c in data:
        print(f"  - {c['name']}: policy={c['policy']}")

    # This should only return 1
    assert len(data) == 1, (
        f"Expected 1 container with policy=auto, got {len(data)}: {[c['name'] for c in data]}"
    )
    assert data[0]["policy"] == "auto"
