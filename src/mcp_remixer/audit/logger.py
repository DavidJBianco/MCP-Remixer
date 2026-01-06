"""Main audit logger implementation."""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from mcp.types import (
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)

from mcp_remixer.audit.config import AuditConfig
from mcp_remixer.audit.schemas import AuditLogEntry, MCPIdentifiers
from mcp_remixer.audit.truncation import truncate_content

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AuditLogger:
    """Comprehensive audit logger for MCP transactions.

    Logs all MCP protocol messages (requests, responses, notifications, errors)
    to a JSON lines file with optional truncation of large fields.
    """

    def __init__(self, config: AuditConfig) -> None:
        """Initialize the audit logger.

        Args:
            config: Audit configuration.
        """
        self.config = config
        self._file_handle: TextIO | None = None
        self._client_info: dict[str, Any] = {}
        self._request_timestamps: dict[str | int, datetime] = {}
        self._session_id: str | None = None

    def start(self) -> None:
        """Initialize the audit logger and open the log file."""
        if not self.config.enabled:
            return

        # Generate a unique session ID for this proxy session
        self._session_id = str(uuid.uuid4())

        if self.config.log_file:
            try:
                # Ensure parent directory exists
                self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
                self._file_handle = open(
                    self.config.log_file, "a", encoding="utf-8"
                )
                logger.info(
                    f"Audit logging enabled, session_id={self._session_id}, "
                    f"writing to: {self.config.log_file}"
                )
            except OSError as e:
                logger.error(f"Failed to open audit log file: {e}")
                self._file_handle = None
        else:
            logger.warning("Audit logging enabled but no log_file specified")

    def stop(self) -> None:
        """Close the audit logger and flush any pending writes."""
        if self._file_handle:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except OSError as e:
                logger.error(f"Error closing audit log file: {e}")
            finally:
                self._file_handle = None

    def set_client_info(
        self, client_name: str | None, client_version: str | None
    ) -> None:
        """Store client info from initialization.

        Args:
            client_name: The client's name.
            client_version: The client's version.
        """
        self._client_info = {
            "name": client_name,
            "version": client_version,
        }

    def log_inbound(self, message: JSONRPCMessage) -> None:
        """Log an inbound message (from client).

        Args:
            message: The JSON-RPC message received from the client.
        """
        if not self.config.enabled or not self._file_handle:
            return

        root = message.root

        if isinstance(root, JSONRPCRequest):
            self._log_request(root, "inbound")
        elif isinstance(root, JSONRPCNotification):
            self._log_notification(root, "inbound")
        elif isinstance(root, JSONRPCResponse):
            self._log_response(root, "inbound")
        elif isinstance(root, JSONRPCError):
            self._log_error(root, "inbound")

    def log_outbound(self, message: JSONRPCMessage) -> None:
        """Log an outbound message (to client).

        Args:
            message: The JSON-RPC message being sent to the client.
        """
        if not self.config.enabled or not self._file_handle:
            return

        root = message.root

        if isinstance(root, JSONRPCRequest):
            self._log_request(root, "outbound")
        elif isinstance(root, JSONRPCNotification):
            self._log_notification(root, "outbound")
        elif isinstance(root, JSONRPCResponse):
            self._log_response(root, "outbound")
        elif isinstance(root, JSONRPCError):
            self._log_error(root, "outbound")

    def _log_request(
        self, req: JSONRPCRequest, direction: str
    ) -> None:
        """Log a JSON-RPC request.

        Args:
            req: The request to log.
            direction: "inbound" or "outbound".
        """
        if not self.config.log_requests:
            return

        # Track timestamp for response correlation
        self._request_timestamps[req.id] = datetime.now(timezone.utc)

        # Extract progress token if present
        progress_token = None
        params_dict = {}
        if req.params:
            if isinstance(req.params, dict):
                params_dict = req.params
                meta = req.params.get("_meta", {})
                if isinstance(meta, dict):
                    progress_token = meta.get("progressToken")
            else:
                # params might be a Pydantic model
                try:
                    params_dict = req.params.model_dump() if hasattr(req.params, 'model_dump') else dict(req.params)
                except (TypeError, ValueError):
                    params_dict = {"_raw": str(req.params)}

        # Check for initialize request to capture client info
        if req.method == "initialize" and params_dict:
            client_info = params_dict.get("clientInfo", {})
            if isinstance(client_info, dict):
                self.set_client_info(
                    client_info.get("name"),
                    client_info.get("version"),
                )

        content = {
            "method": req.method,
            "params": params_dict,
        }

        # Apply truncation if enabled
        is_truncated = False
        if self.config.truncate:
            content, is_truncated = truncate_content(
                content,
                self.config.max_content_length,
                self.config.truncation_marker,
            )

        entry = AuditLogEntry(
            direction=direction,
            message_type="request",
            method=req.method,
            identifiers=MCPIdentifiers(
                session_id=self._session_id,
                request_id=req.id,
                progress_token=progress_token,
                client_name=self._client_info.get("name"),
                client_version=self._client_info.get("version"),
            ),
            content=content,
            isTruncated=is_truncated,
        )

        self._write_entry(entry)

    def _log_response(
        self, resp: JSONRPCResponse, direction: str
    ) -> None:
        """Log a JSON-RPC response.

        Args:
            resp: The response to log.
            direction: "inbound" or "outbound".
        """
        if not self.config.log_responses:
            return

        # Calculate processing time
        processing_time = None
        req_time = self._request_timestamps.pop(resp.id, None)
        if req_time:
            delta = datetime.now(timezone.utc) - req_time
            processing_time = delta.total_seconds() * 1000

        result_dict = resp.result
        if hasattr(result_dict, 'model_dump'):
            result_dict = result_dict.model_dump()
        elif not isinstance(result_dict, dict):
            result_dict = {"_raw": result_dict}

        content = {"result": result_dict}

        # Apply truncation if enabled
        is_truncated = False
        if self.config.truncate:
            content, is_truncated = truncate_content(
                content,
                self.config.max_content_length,
                self.config.truncation_marker,
            )

        entry = AuditLogEntry(
            direction=direction,
            message_type="response",
            identifiers=MCPIdentifiers(
                session_id=self._session_id,
                request_id=resp.id,
                client_name=self._client_info.get("name"),
                client_version=self._client_info.get("version"),
            ),
            content=content,
            isTruncated=is_truncated,
            processing_time_ms=processing_time,
        )

        self._write_entry(entry)

    def _log_error(
        self, err: JSONRPCError, direction: str
    ) -> None:
        """Log a JSON-RPC error response.

        Args:
            err: The error to log.
            direction: "inbound" or "outbound".
        """
        if not self.config.log_errors:
            return

        # Calculate processing time
        processing_time = None
        req_time = self._request_timestamps.pop(err.id, None)
        if req_time:
            delta = datetime.now(timezone.utc) - req_time
            processing_time = delta.total_seconds() * 1000

        error_dict = err.error
        if hasattr(error_dict, 'model_dump'):
            error_dict = error_dict.model_dump()
        elif not isinstance(error_dict, dict):
            error_dict = {"message": str(error_dict)}

        content = {"error": error_dict}

        # Apply truncation if enabled
        is_truncated = False
        if self.config.truncate:
            content, is_truncated = truncate_content(
                content,
                self.config.max_content_length,
                self.config.truncation_marker,
            )

        error_code = None
        if isinstance(err.error, dict):
            error_code = err.error.get("code")
        elif hasattr(err.error, "code"):
            error_code = err.error.code

        entry = AuditLogEntry(
            direction=direction,
            message_type="error",
            identifiers=MCPIdentifiers(
                session_id=self._session_id,
                request_id=err.id,
                client_name=self._client_info.get("name"),
                client_version=self._client_info.get("version"),
            ),
            content=content,
            isTruncated=is_truncated,
            processing_time_ms=processing_time,
            error_code=error_code,
        )

        self._write_entry(entry)

    def _log_notification(
        self, notif: JSONRPCNotification, direction: str
    ) -> None:
        """Log a JSON-RPC notification.

        Args:
            notif: The notification to log.
            direction: "inbound" or "outbound".
        """
        if not self.config.log_notifications:
            return

        params_dict = {}
        if notif.params:
            if isinstance(notif.params, dict):
                params_dict = notif.params
            elif hasattr(notif.params, 'model_dump'):
                params_dict = notif.params.model_dump()
            else:
                try:
                    params_dict = dict(notif.params)
                except (TypeError, ValueError):
                    params_dict = {"_raw": str(notif.params)}

        content = {
            "method": notif.method,
            "params": params_dict,
        }

        # Apply truncation if enabled
        is_truncated = False
        if self.config.truncate:
            content, is_truncated = truncate_content(
                content,
                self.config.max_content_length,
                self.config.truncation_marker,
            )

        entry = AuditLogEntry(
            direction=direction,
            message_type="notification",
            method=notif.method,
            identifiers=MCPIdentifiers(
                session_id=self._session_id,
                client_name=self._client_info.get("name"),
                client_version=self._client_info.get("version"),
            ),
            content=content,
            isTruncated=is_truncated,
        )

        self._write_entry(entry)

    def _write_entry(self, entry: AuditLogEntry) -> None:
        """Write an audit log entry to the file.

        Args:
            entry: The log entry to write.
        """
        if not self._file_handle:
            return

        try:
            indent = 2 if self.config.pretty_print else None
            json_str = entry.model_dump_json(indent=indent)

            self._file_handle.write(json_str + "\n")
            self._file_handle.flush()
        except OSError as e:
            logger.error(f"Failed to write audit log entry: {e}")
