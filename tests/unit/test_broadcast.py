# Feature: live-poll-app, Property 8: WebSocket broadcast reaches all connected clients
"""Property-based test verifying that _broadcast_websocket delivers a message
to every connected client in the active_connections set.

**Validates: Requirements 3.1, 6.4, 6.5**
"""

import asyncio
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st


@given(n=st.integers(min_value=1, max_value=20))
@settings(max_examples=100, deadline=None)
def test_broadcast_reaches_all_connected_clients(n: int) -> None:
    """For any N (1-20) connected WebSocket clients, calling _broadcast_websocket
    must invoke send_text with the message on every single connection."""

    # Create N mock WebSocket connections with async send_text
    mock_connections = set()
    for _ in range(n):
        ws = AsyncMock()
        ws.send_text = AsyncMock()
        mock_connections.add(ws)

    message = '{"event": "vote_update", "poll": {"poll_id": "test"}}'

    # Patch active_connections with our mock set
    with patch("app.routers.websocket.active_connections", new=mock_connections.copy()):
        from app.services.broadcast import _broadcast_websocket

        asyncio.run(_broadcast_websocket(message))

    # Assert ALL N connections received the message
    for ws in mock_connections:
        ws.send_text.assert_called_once_with(message)
