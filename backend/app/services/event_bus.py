"""Simple SSE event bus for broadcasting TideWatch runtime events."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)


class EventBus:
    """Lightweight async pub/sub for server-sent events."""

    def __init__(self) -> None:
        self._listeners: Set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[str]:
        """Register a new listener and return its queue."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        async with self._lock:
            self._listeners.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        """Remove a listener when the stream disconnects."""
        async with self._lock:
            self._listeners.discard(queue)

    async def publish(self, event: Dict[str, Any]) -> None:
        """Broadcast an event to all listeners."""
        if not self._listeners:
            return

        payload = json.dumps(
            {
                **event,
                "timestamp": event.get("timestamp")
                or datetime.now(timezone.utc).isoformat(),
            }
        )

        async with self._lock:
            dead_queues = []
            # Create a copy of listeners to avoid modification during iteration
            for queue in list(self._listeners):
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    logger.warning("Event queue full, removing slow consumer")
                    dead_queues.append(queue)

            # Remove slow consumers
            for queue in dead_queues:
                self._listeners.discard(queue)


event_bus = EventBus()

__all__ = ["event_bus", "EventBus"]
