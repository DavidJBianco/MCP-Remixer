"""Pydantic models for audit log entries."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer


class MCPIdentifiers(BaseModel):
    """MCP protocol identifiers for correlation."""

    session_id: str | None = None  # Globally unique UUID for this proxy session
    request_id: str | int | None = None  # Client-generated, unique within session
    progress_token: str | int | None = None
    client_name: str | None = None
    client_version: str | None = None


class AuditLogEntry(BaseModel):
    """A single audit log entry.

    Attributes:
        timestamp: ISO 8601 timestamp of when the message was logged.
        direction: Whether the message was inbound (from client) or outbound (to client).
        message_type: The type of JSON-RPC message.
        method: The RPC method name (e.g., "tools/call", "initialize").
        identifiers: MCP protocol identifiers for correlation.
        content: The message content (potentially with truncated fields).
        isTruncated: True if any field in content was truncated.
        processing_time_ms: Time to process the request (for responses).
        error_code: JSON-RPC error code (for error responses).
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    direction: Literal["inbound", "outbound"]
    message_type: Literal["request", "response", "notification", "error"]
    method: str | None = None
    identifiers: MCPIdentifiers = Field(default_factory=MCPIdentifiers)
    content: dict[str, Any] = Field(default_factory=dict)
    isTruncated: bool = False
    processing_time_ms: float | None = None
    error_code: int | None = None

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        """Serialize timestamp to ISO 8601 format with Z suffix."""
        return value.isoformat().replace("+00:00", "Z")
