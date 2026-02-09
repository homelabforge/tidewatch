"""Homepage widget API endpoints."""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.container import Container
from app.models.history import UpdateHistory
from app.services.auth import require_auth

router = APIRouter()


@router.get("/widget", response_class=HTMLResponse)
async def get_widget(
    _admin: dict | None = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    """Get Homepage widget HTML.

    Returns an HTML widget showing:
    - Total containers
    - Updates applied (successful)
    - Updates skipped (no updates available)
    - Updates failed
    """
    # Get container stats
    containers_result = await db.execute(select(func.count(Container.id)))
    total_containers = containers_result.scalar() or 0

    # Get containers with updates available
    updates_available_result = await db.execute(
        select(func.count(Container.id)).where(Container.update_available)
    )
    updates_available = updates_available_result.scalar() or 0

    # Get history stats
    successful_result = await db.execute(
        select(func.count(UpdateHistory.id)).where(UpdateHistory.status == "success")
    )
    successful = successful_result.scalar() or 0

    failed_result = await db.execute(
        select(func.count(UpdateHistory.id)).where(UpdateHistory.status == "failed")
    )
    failed = failed_result.scalar() or 0

    # Calculate skipped (containers without updates)
    skipped = total_containers - updates_available

    # Generate HTML widget
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TideWatch Status</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: transparent;
            padding: 12px;
        }}

        .widget {{
            background: linear-gradient(135deg, #14b8a6 0%, #0d9488 100%);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            color: white;
        }}

        .header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
            padding-bottom: 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.2);
        }}

        .icon {{
            width: 32px;
            height: 32px;
            background: rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
        }}

        .title {{
            font-size: 18px;
            font-weight: 600;
        }}

        .stats {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }}

        .stat {{
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(10px);
            border-radius: 8px;
            padding: 12px;
            transition: transform 0.2s;
        }}

        .stat:hover {{
            transform: translateY(-2px);
            background: rgba(255, 255, 255, 0.2);
        }}

        .stat-label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            opacity: 0.9;
            margin-bottom: 6px;
        }}

        .stat-value {{
            font-size: 24px;
            font-weight: 700;
            line-height: 1;
        }}

        .stat-icon {{
            float: right;
            opacity: 0.6;
            font-size: 18px;
        }}

        .footer {{
            margin-top: 16px;
            padding-top: 12px;
            border-top: 1px solid rgba(255, 255, 255, 0.2);
            text-align: center;
            font-size: 11px;
            opacity: 0.8;
        }}

        @media (max-width: 400px) {{
            .stats {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="widget">
        <div class="header">
            <div class="icon">🌊</div>
            <div class="title">TideWatch</div>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-label">
                    <span class="stat-icon">📦</span>
                    Containers
                </div>
                <div class="stat-value">{total_containers}</div>
            </div>

            <div class="stat">
                <div class="stat-label">
                    <span class="stat-icon">✅</span>
                    Updated
                </div>
                <div class="stat-value">{successful}</div>
            </div>

            <div class="stat">
                <div class="stat-label">
                    <span class="stat-icon">⏭️</span>
                    Skipped
                </div>
                <div class="stat-value">{skipped}</div>
            </div>

            <div class="stat">
                <div class="stat-label">
                    <span class="stat-icon">❌</span>
                    Failed
                </div>
                <div class="stat-value">{failed}</div>
            </div>
        </div>

        <div class="footer">
            Security-driven container updates
        </div>
    </div>
</body>
</html>
"""

    return HTMLResponse(content=html)


@router.get("/widget/data")
async def get_widget_data(
    _admin: dict | None = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get widget data as JSON for custom integrations."""
    # Get container stats
    containers_result = await db.execute(select(func.count(Container.id)))
    total_containers = containers_result.scalar() or 0

    # Get containers with updates available
    updates_available_result = await db.execute(
        select(func.count(Container.id)).where(Container.update_available)
    )
    updates_available = updates_available_result.scalar() or 0

    # Get history stats
    successful_result = await db.execute(
        select(func.count(UpdateHistory.id)).where(UpdateHistory.status == "success")
    )
    successful = successful_result.scalar() or 0

    failed_result = await db.execute(
        select(func.count(UpdateHistory.id)).where(UpdateHistory.status == "failed")
    )
    failed = failed_result.scalar() or 0

    # Calculate skipped
    skipped = total_containers - updates_available

    return {
        "containers": total_containers,
        "updated": successful,
        "skipped": skipped,
        "failed": failed,
        "updates_available": updates_available,
    }
