"""Stream wrappers for audit logging.

These wrappers intercept messages flowing through MCP transport streams
and log them for auditing purposes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, TypeVar

from mcp.shared.message import SessionMessage

from mcp_remixer.audit.logger import AuditLogger

if TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream


T = TypeVar("T")


class AuditedReceiveStream:
    """Wrapper that logs messages received from the client.

    This wrapper intercepts all inbound messages and passes them to the
    audit logger before returning them to the caller.
    """

    def __init__(
        self,
        inner: MemoryObjectReceiveStream[SessionMessage | Exception],
        audit_logger: AuditLogger,
    ) -> None:
        """Initialize the audited receive stream.

        Args:
            inner: The underlying receive stream to wrap.
            audit_logger: The audit logger to use for logging messages.
        """
        self._inner = inner
        self._audit_logger = audit_logger

    async def receive(self) -> SessionMessage | Exception:
        """Receive a message from the stream and log it.

        Returns:
            The received message or exception.
        """
        message = await self._inner.receive()
        if isinstance(message, SessionMessage):
            self._audit_logger.log_inbound(message.message)
        return message

    def __aiter__(self) -> AsyncIterator[SessionMessage | Exception]:
        """Return an async iterator over the stream."""
        return self

    async def __anext__(self) -> SessionMessage | Exception:
        """Get the next message from the stream.

        Returns:
            The next message.

        Raises:
            StopAsyncIteration: When the stream is exhausted.
        """
        try:
            return await self.receive()
        except Exception as e:
            # Check if this is an end-of-stream condition
            if "ClosedResourceError" in type(e).__name__ or "EndOfStream" in type(e).__name__:
                raise StopAsyncIteration from e
            raise

    async def aclose(self) -> None:
        """Close the underlying stream."""
        await self._inner.aclose()

    async def __aenter__(self):
        """Enter the async context manager."""
        if hasattr(self._inner, "__aenter__"):
            await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager."""
        if hasattr(self._inner, "__aexit__"):
            return await self._inner.__aexit__(exc_type, exc_val, exc_tb)
        return None

    def __getattr__(self, name: str):
        """Delegate unknown attributes to the inner stream."""
        return getattr(self._inner, name)


class AuditedSendStream:
    """Wrapper that logs messages sent to the client.

    This wrapper intercepts all outbound messages and passes them to the
    audit logger before sending them.
    """

    def __init__(
        self,
        inner: MemoryObjectSendStream[SessionMessage],
        audit_logger: AuditLogger,
    ) -> None:
        """Initialize the audited send stream.

        Args:
            inner: The underlying send stream to wrap.
            audit_logger: The audit logger to use for logging messages.
        """
        self._inner = inner
        self._audit_logger = audit_logger

    async def send(self, message: SessionMessage) -> None:
        """Log and send a message to the stream.

        Args:
            message: The message to send.
        """
        self._audit_logger.log_outbound(message.message)
        await self._inner.send(message)

    async def aclose(self) -> None:
        """Close the underlying stream."""
        await self._inner.aclose()

    async def __aenter__(self):
        """Enter the async context manager."""
        if hasattr(self._inner, "__aenter__"):
            await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager."""
        if hasattr(self._inner, "__aexit__"):
            return await self._inner.__aexit__(exc_type, exc_val, exc_tb)
        return None

    def __getattr__(self, name: str):
        """Delegate unknown attributes to the inner stream."""
        return getattr(self._inner, name)
