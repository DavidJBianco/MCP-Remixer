"""Tests for audit stream wrappers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_remixer.audit.config import AuditConfig
from mcp_remixer.audit.logger import AuditLogger
from mcp_remixer.audit.streams import AuditedReceiveStream, AuditedSendStream


class TestAuditedReceiveStream:
    """Tests for AuditedReceiveStream."""

    @pytest.fixture
    def mock_inner_stream(self):
        """Create a mock inner stream."""
        stream = AsyncMock()
        return stream

    @pytest.fixture
    def mock_audit_logger(self):
        """Create a mock audit logger."""
        logger = MagicMock(spec=AuditLogger)
        return logger

    @pytest.mark.asyncio
    async def test_receive_logs_session_message(
        self, mock_inner_stream, mock_audit_logger
    ):
        """SessionMessage should be logged when received."""
        # Create mock SessionMessage
        session_message = MagicMock()
        session_message.message = MagicMock()
        mock_inner_stream.receive.return_value = session_message

        # Patch SessionMessage check
        with patch(
            "mcp_remixer.audit.streams.SessionMessage", type(session_message)
        ):
            stream = AuditedReceiveStream(mock_inner_stream, mock_audit_logger)
            result = await stream.receive()

        assert result == session_message
        mock_audit_logger.log_inbound.assert_called_once_with(
            session_message.message
        )

    @pytest.mark.asyncio
    async def test_receive_passes_through_exception(
        self, mock_inner_stream, mock_audit_logger
    ):
        """Exception should be passed through without logging."""
        exception = Exception("test error")
        mock_inner_stream.receive.return_value = exception

        stream = AuditedReceiveStream(mock_inner_stream, mock_audit_logger)
        result = await stream.receive()

        assert result == exception
        mock_audit_logger.log_inbound.assert_not_called()

    @pytest.mark.asyncio
    async def test_aclose_delegates(self, mock_inner_stream, mock_audit_logger):
        """aclose should delegate to inner stream."""
        stream = AuditedReceiveStream(mock_inner_stream, mock_audit_logger)
        await stream.aclose()

        mock_inner_stream.aclose.assert_called_once()

    def test_getattr_delegates(self, mock_inner_stream, mock_audit_logger):
        """Unknown attributes should delegate to inner stream."""
        mock_inner_stream.custom_attr = "test_value"

        stream = AuditedReceiveStream(mock_inner_stream, mock_audit_logger)
        assert stream.custom_attr == "test_value"

    @pytest.mark.asyncio
    async def test_async_iteration(self, mock_inner_stream, mock_audit_logger):
        """Stream should support async iteration."""
        session_message = MagicMock()
        session_message.message = MagicMock()

        # First call returns message, second raises to stop iteration
        mock_inner_stream.receive.side_effect = [
            session_message,
            Exception("EndOfStream"),
        ]

        with patch(
            "mcp_remixer.audit.streams.SessionMessage", type(session_message)
        ):
            stream = AuditedReceiveStream(mock_inner_stream, mock_audit_logger)

            # First iteration should work
            result = await stream.__anext__()
            assert result == session_message


class TestAuditedSendStream:
    """Tests for AuditedSendStream."""

    @pytest.fixture
    def mock_inner_stream(self):
        """Create a mock inner stream."""
        stream = AsyncMock()
        return stream

    @pytest.fixture
    def mock_audit_logger(self):
        """Create a mock audit logger."""
        logger = MagicMock(spec=AuditLogger)
        return logger

    @pytest.mark.asyncio
    async def test_send_logs_before_sending(
        self, mock_inner_stream, mock_audit_logger
    ):
        """Message should be logged before sending."""
        session_message = MagicMock()
        session_message.message = MagicMock()

        stream = AuditedSendStream(mock_inner_stream, mock_audit_logger)
        await stream.send(session_message)

        # Verify logging happened
        mock_audit_logger.log_outbound.assert_called_once_with(
            session_message.message
        )
        # Verify send happened
        mock_inner_stream.send.assert_called_once_with(session_message)

    @pytest.mark.asyncio
    async def test_send_order(self, mock_inner_stream, mock_audit_logger):
        """Logging should happen before sending."""
        call_order = []

        def log_call(*args):
            call_order.append("log")

        async def send_call(*args):
            call_order.append("send")

        mock_audit_logger.log_outbound.side_effect = log_call
        mock_inner_stream.send.side_effect = send_call

        session_message = MagicMock()
        session_message.message = MagicMock()

        stream = AuditedSendStream(mock_inner_stream, mock_audit_logger)
        await stream.send(session_message)

        assert call_order == ["log", "send"]

    @pytest.mark.asyncio
    async def test_aclose_delegates(self, mock_inner_stream, mock_audit_logger):
        """aclose should delegate to inner stream."""
        stream = AuditedSendStream(mock_inner_stream, mock_audit_logger)
        await stream.aclose()

        mock_inner_stream.aclose.assert_called_once()

    def test_getattr_delegates(self, mock_inner_stream, mock_audit_logger):
        """Unknown attributes should delegate to inner stream."""
        mock_inner_stream.custom_attr = "test_value"

        stream = AuditedSendStream(mock_inner_stream, mock_audit_logger)
        assert stream.custom_attr == "test_value"


class TestStreamIntegration:
    """Integration tests for stream wrappers."""

    @pytest.mark.asyncio
    async def test_bidirectional_calls_logger(self, tmp_path):
        """Both inbound and outbound streams should call the audit logger."""
        # Use mock logger to verify calls without needing real MCP types
        mock_logger = MagicMock(spec=AuditLogger)

        # Create mock streams
        inner_receive = AsyncMock()
        inner_send = AsyncMock()

        # Create wrapped streams
        receive_stream = AuditedReceiveStream(inner_receive, mock_logger)
        send_stream = AuditedSendStream(inner_send, mock_logger)

        # Create mock messages
        inbound_message = MagicMock()
        inbound_message.message = MagicMock()

        outbound_message = MagicMock()
        outbound_message.message = MagicMock()

        inner_receive.receive.return_value = inbound_message

        # Simulate receiving
        with patch(
            "mcp_remixer.audit.streams.SessionMessage", type(inbound_message)
        ):
            await receive_stream.receive()

        # Simulate sending
        await send_stream.send(outbound_message)

        # Verify logger was called for both
        mock_logger.log_inbound.assert_called_once_with(inbound_message.message)
        mock_logger.log_outbound.assert_called_once_with(outbound_message.message)
