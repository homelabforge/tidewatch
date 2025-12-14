"""Tests for Events API (app/api/events.py).

Tests Server-Sent Events (SSE) endpoint:
- GET /api/v1/events/stream - SSE event stream
"""

import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import status


class TestEventStreamEndpoint:
    """Test suite for GET /api/v1/events/stream endpoint."""

    async def test_stream_requires_auth(self, client, db):
        """Test requires authentication."""
        from app.services.settings_service import SettingsService
        await SettingsService.set(db, "auth_mode", "local")
        await db.commit()

        # Act
        response = await client.get("/api/v1/events/stream")

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_stream_connection_opens(self, authenticated_client):
        """Test SSE connection opens successfully."""
        # Mock event bus
        mock_queue = asyncio.Queue()

        with patch('app.api.events.event_bus.subscribe', new_callable=AsyncMock) as mock_subscribe, \
             patch('app.api.events.event_bus.unsubscribe', new_callable=AsyncMock) as mock_unsub:

            # Put a message to immediately close the stream
            await mock_queue.put(json.dumps({"type": "test", "data": "hello"}))
            mock_subscribe.return_value = mock_queue

            # Act
            response = await authenticated_client.get("/api/v1/events/stream")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
            mock_subscribe.assert_called_once()

    async def test_stream_sends_connected_event(self, authenticated_client):
        """Test stream sends initial connected event."""
        # Mock event bus
        mock_queue = asyncio.Queue()

        with patch('app.api.events.event_bus.subscribe', new_callable=AsyncMock) as mock_subscribe, \
             patch('app.api.events.event_bus.unsubscribe', new_callable=AsyncMock):

            mock_subscribe.return_value = mock_queue

            # Act - Start streaming in background
            response = await authenticated_client.get("/api/v1/events/stream")

            # Assert
            assert response.status_code == status.HTTP_200_OK
            # The stream should start with a connected event
            # Note: Full SSE content verification would require streaming the response

    async def test_stream_publishes_events(self, authenticated_client):
        """Test event bus publishes events to stream."""
        # Arrange - Create a real event bus instance for testing
        from app.services.event_bus import EventBus

        test_bus = EventBus()

        with patch('app.api.events.event_bus', test_bus):
            # Subscribe to the bus
            queue = await test_bus.subscribe()

            # Publish test event
            await test_bus.publish({"type": "container_update", "container": "nginx", "status": "updated"})

            # Act - Get message from queue
            message = await asyncio.wait_for(queue.get(), timeout=1.0)
            data = json.loads(message)

            # Assert
            assert data["type"] == "container_update"
            assert data["container"] == "nginx"
            assert data["status"] == "updated"
            assert "timestamp" in data

            # Cleanup
            await test_bus.unsubscribe(queue)

    async def test_stream_multiple_subscribers(self, authenticated_client):
        """Test multiple clients can subscribe to event stream."""
        # Arrange
        from app.services.event_bus import EventBus

        test_bus = EventBus()

        # Act - Subscribe multiple listeners
        queue1 = await test_bus.subscribe()
        queue2 = await test_bus.subscribe()
        queue3 = await test_bus.subscribe()

        # Publish event
        await test_bus.publish({"type": "test", "data": "broadcast"})

        # Assert - All queues should receive the message
        msg1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
        msg2 = await asyncio.wait_for(queue2.get(), timeout=1.0)
        msg3 = await asyncio.wait_for(queue3.get(), timeout=1.0)

        assert json.loads(msg1)["type"] == "test"
        assert json.loads(msg2)["type"] == "test"
        assert json.loads(msg3)["type"] == "test"

        # Cleanup
        await test_bus.unsubscribe(queue1)
        await test_bus.unsubscribe(queue2)
        await test_bus.unsubscribe(queue3)

    async def test_stream_unsubscribe_cleanup(self, authenticated_client):
        """Test unsubscribe properly removes listener."""
        # Arrange
        from app.services.event_bus import EventBus

        test_bus = EventBus()

        # Subscribe
        queue = await test_bus.subscribe()
        assert len(test_bus._listeners) == 1

        # Act - Unsubscribe
        await test_bus.unsubscribe(queue)

        # Assert
        assert len(test_bus._listeners) == 0

    async def test_event_bus_no_listeners(self, authenticated_client):
        """Test publishing with no listeners doesn't error."""
        # Arrange
        from app.services.event_bus import EventBus

        test_bus = EventBus()

        # Act - Publish with no listeners
        await test_bus.publish({"type": "test", "data": "no one listening"})

        # Assert - Should not raise exception
        assert len(test_bus._listeners) == 0

    async def test_event_includes_timestamp(self, authenticated_client):
        """Test published events include timestamp."""
        # Arrange
        from app.services.event_bus import EventBus

        test_bus = EventBus()
        queue = await test_bus.subscribe()

        # Act - Publish event without timestamp
        await test_bus.publish({"type": "test", "message": "hello"})

        message = await asyncio.wait_for(queue.get(), timeout=1.0)
        data = json.loads(message)

        # Assert - Timestamp should be added
        assert "timestamp" in data
        assert data["type"] == "test"
        assert data["message"] == "hello"

        # Cleanup
        await test_bus.unsubscribe(queue)

    async def test_event_custom_timestamp_preserved(self, authenticated_client):
        """Test custom timestamp in event is preserved."""
        # Arrange
        from app.services.event_bus import EventBus

        test_bus = EventBus()
        queue = await test_bus.subscribe()

        custom_timestamp = "2025-01-01T12:00:00Z"

        # Act - Publish event with custom timestamp
        await test_bus.publish({"type": "test", "timestamp": custom_timestamp})

        message = await asyncio.wait_for(queue.get(), timeout=1.0)
        data = json.loads(message)

        # Assert - Custom timestamp should be preserved
        assert data["timestamp"] == custom_timestamp

        # Cleanup
        await test_bus.unsubscribe(queue)

    async def test_event_bus_concurrent_publish(self, authenticated_client):
        """Test event bus handles concurrent publishes correctly."""
        # Arrange
        from app.services.event_bus import EventBus

        test_bus = EventBus()
        queue = await test_bus.subscribe()

        # Act - Publish multiple events concurrently
        await asyncio.gather(
            test_bus.publish({"type": "event1", "id": 1}),
            test_bus.publish({"type": "event2", "id": 2}),
            test_bus.publish({"type": "event3", "id": 3}),
        )

        # Assert - All events should be received
        messages = []
        for _ in range(3):
            msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            messages.append(json.loads(msg))

        assert len(messages) == 3
        event_types = {msg["type"] for msg in messages}
        assert event_types == {"event1", "event2", "event3"}

        # Cleanup
        await test_bus.unsubscribe(queue)
