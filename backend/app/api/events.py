"""Event streaming endpoints for real-time TideWatch updates."""

import asyncio
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse

from app.services.event_bus import event_bus
from app.services.auth import require_auth

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream_events(
    request: Request,
    admin: Optional[dict] = Depends(require_auth),
) -> StreamingResponse:
    """Server-sent events stream for live update notifications."""

    async def event_generator() -> AsyncGenerator[str, None]:
        queue = await event_bus.subscribe()
        try:
            # Initial ready event for clients
            yield 'data: {"type":"connected"}\n\n'

            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep the connection alive
                    yield "event: ping\ndata: {}\n\n"
        finally:
            await event_bus.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
