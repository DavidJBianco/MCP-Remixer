"""Tests for audit logger."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_remixer.audit.config import AuditConfig
from mcp_remixer.audit.logger import AuditLogger
from mcp_remixer.audit.schemas import AuditLogEntry, MCPIdentifiers


class TestAuditLogger:
    """Tests for AuditLogger class."""

    def test_init_with_config(self):
        """Logger should initialize with config."""
        config = AuditConfig(enabled=True)
        logger = AuditLogger(config)
        assert logger.config == config

    def test_start_creates_file(self, tmp_path):
        """Start should create log file."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(enabled=True, log_file=log_file)
        logger = AuditLogger(config)

        logger.start()
        assert log_file.exists()
        logger.stop()

    def test_start_creates_parent_dirs(self, tmp_path):
        """Start should create parent directories."""
        log_file = tmp_path / "subdir" / "nested" / "audit.jsonl"
        config = AuditConfig(enabled=True, log_file=log_file)
        logger = AuditLogger(config)

        logger.start()
        assert log_file.exists()
        logger.stop()

    def test_start_disabled_does_nothing(self, tmp_path):
        """Start with disabled config should not create file."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(enabled=False, log_file=log_file)
        logger = AuditLogger(config)

        logger.start()
        assert not log_file.exists()

    def test_stop_flushes_and_closes(self, tmp_path):
        """Stop should flush and close the file."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(enabled=True, log_file=log_file)
        logger = AuditLogger(config)

        logger.start()
        logger.stop()
        # File should be closed, trying to write should not work
        assert logger._file_handle is None

    def test_set_client_info(self):
        """Client info should be stored."""
        config = AuditConfig(enabled=True)
        logger = AuditLogger(config)

        logger.set_client_info("test-client", "1.0.0")
        assert logger._client_info["name"] == "test-client"
        assert logger._client_info["version"] == "1.0.0"


class TestAuditLoggerLogging:
    """Tests for actual logging functionality."""

    @pytest.fixture
    def logger_with_file(self, tmp_path):
        """Create a logger with a temp file."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(enabled=True, log_file=log_file)
        logger = AuditLogger(config)
        logger.start()
        yield logger, log_file
        logger.stop()

    def test_log_request(self, logger_with_file):
        """Request should be logged with correct fields."""
        logger, log_file = logger_with_file

        # Create mock request
        request = MagicMock()
        request.id = 1
        request.method = "tools/call"
        request.params = {"name": "test_tool", "arguments": {"arg": "value"}}

        message = MagicMock()
        message.root = request

        # Need to make isinstance work
        with patch("mcp_remixer.audit.logger.JSONRPCRequest", type(request)):
            logger.log_inbound(message)

        # Read and verify
        content = log_file.read_text()
        assert content.strip()  # Not empty
        entry = json.loads(content.strip())
        assert entry["direction"] == "inbound"
        assert entry["message_type"] == "request"
        assert entry["method"] == "tools/call"
        assert entry["identifiers"]["request_id"] == 1

    def test_log_response_with_processing_time(self, logger_with_file):
        """Response should include processing time."""
        logger, log_file = logger_with_file

        # First log a request to set up timestamp
        logger._request_timestamps[42] = datetime.now(timezone.utc)

        # Create mock response
        response = MagicMock()
        response.id = 42
        response.result = {"content": [{"type": "text", "text": "result"}]}

        message = MagicMock()
        message.root = response

        with patch("mcp_remixer.audit.logger.JSONRPCResponse", type(response)):
            logger.log_outbound(message)

        content = log_file.read_text()
        entry = json.loads(content.strip())
        assert entry["message_type"] == "response"
        assert entry["processing_time_ms"] is not None
        assert entry["processing_time_ms"] >= 0

    def test_log_notification(self, logger_with_file):
        """Notification should be logged."""
        logger, log_file = logger_with_file

        notification = MagicMock()
        notification.method = "notifications/tools/list_changed"
        notification.params = {}

        message = MagicMock()
        message.root = notification

        with patch(
            "mcp_remixer.audit.logger.JSONRPCNotification", type(notification)
        ):
            logger.log_inbound(message)

        content = log_file.read_text()
        entry = json.loads(content.strip())
        assert entry["message_type"] == "notification"
        assert entry["method"] == "notifications/tools/list_changed"

    def test_log_error_with_code(self, logger_with_file):
        """Error response should include error code."""
        logger, log_file = logger_with_file

        error = MagicMock()
        error.id = 1
        error.error = MagicMock()
        error.error.code = -32600
        error.error.model_dump = MagicMock(
            return_value={"code": -32600, "message": "Invalid Request"}
        )

        message = MagicMock()
        message.root = error

        with patch("mcp_remixer.audit.logger.JSONRPCError", type(error)):
            logger.log_outbound(message)

        content = log_file.read_text()
        entry = json.loads(content.strip())
        assert entry["message_type"] == "error"
        assert entry["error_code"] == -32600

    def test_client_info_from_initialize(self, logger_with_file):
        """Client info should be extracted from initialize request."""
        logger, log_file = logger_with_file

        request = MagicMock()
        request.id = 0
        request.method = "initialize"
        request.params = {
            "clientInfo": {"name": "test-client", "version": "2.0.0"},
            "capabilities": {},
        }

        message = MagicMock()
        message.root = request

        with patch("mcp_remixer.audit.logger.JSONRPCRequest", type(request)):
            logger.log_inbound(message)

        assert logger._client_info["name"] == "test-client"
        assert logger._client_info["version"] == "2.0.0"

    def test_progress_token_extraction(self, logger_with_file):
        """Progress token should be extracted from _meta."""
        logger, log_file = logger_with_file

        request = MagicMock()
        request.id = 1
        request.method = "tools/call"
        request.params = {
            "_meta": {"progressToken": "token123"},
            "name": "test",
        }

        message = MagicMock()
        message.root = request

        with patch("mcp_remixer.audit.logger.JSONRPCRequest", type(request)):
            logger.log_inbound(message)

        content = log_file.read_text()
        entry = json.loads(content.strip())
        assert entry["identifiers"]["progress_token"] == "token123"


class TestAuditLoggerTruncation:
    """Tests for truncation in audit logger."""

    @pytest.fixture
    def truncating_logger(self, tmp_path):
        """Create a logger with truncation enabled."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(
            enabled=True,
            log_file=log_file,
            truncate=True,
            max_content_length=50,
        )
        logger = AuditLogger(config)
        logger.start()
        yield logger, log_file
        logger.stop()

    def test_truncation_sets_is_truncated(self, truncating_logger):
        """isTruncated should be True when content is truncated."""
        logger, log_file = truncating_logger

        request = MagicMock()
        request.id = 1
        request.method = "tools/call"
        request.params = {"arguments": "x" * 100}  # Large content

        message = MagicMock()
        message.root = request

        with patch("mcp_remixer.audit.logger.JSONRPCRequest", type(request)):
            logger.log_inbound(message)

        content = log_file.read_text()
        entry = json.loads(content.strip())
        assert entry["isTruncated"] is True

    def test_no_truncation_when_disabled(self, tmp_path):
        """isTruncated should be False when truncation disabled."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(
            enabled=True,
            log_file=log_file,
            truncate=False,  # Disabled
        )
        logger = AuditLogger(config)
        logger.start()

        request = MagicMock()
        request.id = 1
        request.method = "tools/call"
        request.params = {"arguments": "x" * 100}

        message = MagicMock()
        message.root = request

        with patch("mcp_remixer.audit.logger.JSONRPCRequest", type(request)):
            logger.log_inbound(message)

        logger.stop()

        content = log_file.read_text()
        entry = json.loads(content.strip())
        assert entry["isTruncated"] is False
        # Full content should be logged
        assert entry["content"]["params"]["arguments"] == "x" * 100


class TestAuditLoggerFiltering:
    """Tests for message type filtering."""

    def test_requests_not_logged_when_disabled(self, tmp_path):
        """Requests should not be logged when log_requests is False."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(
            enabled=True, log_file=log_file, log_requests=False
        )
        logger = AuditLogger(config)
        logger.start()

        request = MagicMock()
        request.id = 1
        request.method = "test"
        request.params = {}

        message = MagicMock()
        message.root = request

        with patch("mcp_remixer.audit.logger.JSONRPCRequest", type(request)):
            logger.log_inbound(message)

        logger.stop()

        content = log_file.read_text()
        assert content == ""

    def test_responses_not_logged_when_disabled(self, tmp_path):
        """Responses should not be logged when log_responses is False."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(
            enabled=True, log_file=log_file, log_responses=False
        )
        logger = AuditLogger(config)
        logger.start()

        response = MagicMock()
        response.id = 1
        response.result = {}

        message = MagicMock()
        message.root = response

        with patch("mcp_remixer.audit.logger.JSONRPCResponse", type(response)):
            logger.log_outbound(message)

        logger.stop()

        content = log_file.read_text()
        assert content == ""

    def test_notifications_not_logged_when_disabled(self, tmp_path):
        """Notifications should not be logged when log_notifications is False."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(
            enabled=True, log_file=log_file, log_notifications=False
        )
        logger = AuditLogger(config)
        logger.start()

        notification = MagicMock()
        notification.method = "test"
        notification.params = {}

        message = MagicMock()
        message.root = notification

        with patch(
            "mcp_remixer.audit.logger.JSONRPCNotification", type(notification)
        ):
            logger.log_inbound(message)

        logger.stop()

        content = log_file.read_text()
        assert content == ""

    def test_errors_not_logged_when_disabled(self, tmp_path):
        """Errors should not be logged when log_errors is False."""
        log_file = tmp_path / "audit.jsonl"
        config = AuditConfig(
            enabled=True, log_file=log_file, log_errors=False
        )
        logger = AuditLogger(config)
        logger.start()

        error = MagicMock()
        error.id = 1
        error.error = {"code": -1, "message": "test"}

        message = MagicMock()
        message.root = error

        with patch("mcp_remixer.audit.logger.JSONRPCError", type(error)):
            logger.log_outbound(message)

        logger.stop()

        content = log_file.read_text()
        assert content == ""
