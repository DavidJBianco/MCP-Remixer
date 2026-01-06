"""Unit tests for upstream connection management."""

import asyncio

import pytest
from unittest.mock import AsyncMock

from mcp_remixer.config import HTTPUpstreamConfig, StdioUpstreamConfig
from mcp_remixer.upstream import UpstreamConnection, UpstreamManager


class TestUpstreamDisconnect:
    """Tests for upstream disconnect handling."""

    @pytest.mark.asyncio
    async def test_disconnect_signals_shutdown_for_task_connections(self):
        """Test that disconnect_all signals shutdown for task-managed connections."""
        manager = UpstreamManager()

        shutdown_event = asyncio.Event()
        task_completed = asyncio.Event()

        async def mock_task():
            await shutdown_event.wait()
            task_completed.set()

        task = asyncio.create_task(mock_task())

        conn = UpstreamConnection(
            name="test",
            config=HTTPUpstreamConfig(name="test", transport="http", url="http://test"),
            session=None,
            _task=task,
            _shutdown_event=shutdown_event,
        )
        manager._connections["test"] = conn

        await manager.disconnect_all()

        # Shutdown should have been signaled
        assert shutdown_event.is_set()
        # Task should have completed
        assert task_completed.is_set()

    @pytest.mark.asyncio
    async def test_disconnect_uses_direct_cleanup_for_stdio(self):
        """Test that disconnect_all uses direct cleanup for STDIO (no task)."""
        manager = UpstreamManager()

        mock_session = AsyncMock()
        mock_session.__aexit__ = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aexit__ = AsyncMock()

        conn = UpstreamConnection(
            name="test",
            config=StdioUpstreamConfig(name="test", transport="stdio", command="echo", args=[]),
            session=mock_session,
            _cm=mock_cm,
            # No _task, _shutdown_event for STDIO
        )
        manager._connections["test"] = conn

        await manager.disconnect_all()

        # Direct cleanup should have been called
        mock_session.__aexit__.assert_called_once_with(None, None, None)
        mock_cm.__aexit__.assert_called_once_with(None, None, None)

    @pytest.mark.asyncio
    async def test_disconnect_waits_for_task_completion(self):
        """Test that disconnect_all waits for task to complete."""
        manager = UpstreamManager()

        shutdown_event = asyncio.Event()
        cleanup_order = []

        async def mock_task():
            await shutdown_event.wait()
            # Simulate some cleanup time
            await asyncio.sleep(0.01)
            cleanup_order.append("task_done")

        task = asyncio.create_task(mock_task())

        conn = UpstreamConnection(
            name="test",
            config=HTTPUpstreamConfig(name="test", transport="http", url="http://test"),
            session=None,
            _task=task,
            _shutdown_event=shutdown_event,
        )
        manager._connections["test"] = conn

        await manager.disconnect_all()
        cleanup_order.append("disconnect_done")

        # Task should complete before disconnect_all returns
        assert cleanup_order == ["task_done", "disconnect_done"]

    @pytest.mark.asyncio
    async def test_disconnect_handles_task_exceptions(self):
        """Test that disconnect_all handles exceptions from tasks gracefully."""
        manager = UpstreamManager()

        shutdown_event = asyncio.Event()

        async def mock_task():
            await shutdown_event.wait()
            raise RuntimeError("Task cleanup failed")

        task = asyncio.create_task(mock_task())

        conn = UpstreamConnection(
            name="test",
            config=HTTPUpstreamConfig(name="test", transport="http", url="http://test"),
            session=None,
            _task=task,
            _shutdown_event=shutdown_event,
        )
        manager._connections["test"] = conn

        # Should not raise (exception is logged as warning)
        await manager.disconnect_all()

        # Connections should still be cleared
        assert len(manager._connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_clears_connections(self):
        """Test that disconnect_all clears the connections dict."""
        manager = UpstreamManager()

        shutdown_event = asyncio.Event()

        async def mock_task():
            await shutdown_event.wait()

        task = asyncio.create_task(mock_task())

        conn = UpstreamConnection(
            name="test",
            config=HTTPUpstreamConfig(name="test", transport="http", url="http://test"),
            session=None,
            _task=task,
            _shutdown_event=shutdown_event,
        )
        manager._connections["test"] = conn

        assert len(manager._connections) == 1
        await manager.disconnect_all()
        assert len(manager._connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_handles_multiple_connections(self):
        """Test that disconnect_all handles multiple connections."""
        manager = UpstreamManager()

        events = []

        async def make_mock_task(name, shutdown_event):
            await shutdown_event.wait()
            events.append(f"{name}_done")

        # Create multiple connections
        for i in range(3):
            shutdown_event = asyncio.Event()
            task = asyncio.create_task(make_mock_task(f"conn{i}", shutdown_event))
            conn = UpstreamConnection(
                name=f"conn{i}",
                config=HTTPUpstreamConfig(name=f"conn{i}", transport="http", url=f"http://test{i}"),
                session=None,
                _task=task,
                _shutdown_event=shutdown_event,
            )
            manager._connections[f"conn{i}"] = conn

        assert len(manager._connections) == 3
        await manager.disconnect_all()
        assert len(manager._connections) == 0
        assert len(events) == 3  # All tasks completed


class TestUpstreamConnectionDataclass:
    """Tests for UpstreamConnection dataclass."""

    def test_connected_property_with_session(self):
        """Test that connected returns True when session exists."""
        conn = UpstreamConnection(
            name="test",
            config=HTTPUpstreamConfig(name="test", transport="http", url="http://test"),
            session=AsyncMock(),
        )
        assert conn.connected is True

    def test_connected_property_without_session(self):
        """Test that connected returns False when session is None."""
        conn = UpstreamConnection(
            name="test",
            config=HTTPUpstreamConfig(name="test", transport="http", url="http://test"),
            session=None,
        )
        assert conn.connected is False

    def test_default_values(self):
        """Test that default values are set correctly."""
        conn = UpstreamConnection(
            name="test",
            config=HTTPUpstreamConfig(name="test", transport="http", url="http://test"),
        )
        assert conn.session is None
        assert conn.tools is None
        assert conn._task is None
        assert conn._ready_event is None
        assert conn._shutdown_event is None
        assert conn._error is None
