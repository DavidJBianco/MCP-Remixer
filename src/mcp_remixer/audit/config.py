"""Audit logging configuration."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AuditConfig:
    """Configuration for audit logging.

    Attributes:
        enabled: Whether audit logging is enabled.
        log_file: Path to the audit log file. Required when enabled.
        truncate: Whether to truncate large fields. Default is False.
        max_content_length: Per-field truncation limit in bytes.
            Only used when truncate is True. Default is 1024.
        truncation_marker: String appended to truncated content.
        log_requests: Whether to log inbound requests.
        log_responses: Whether to log outbound responses.
        log_notifications: Whether to log notifications.
        log_errors: Whether to log error responses.
        pretty_print: Whether to pretty-print JSON output (for debugging).
    """

    enabled: bool = False
    log_file: Path | None = None
    truncate: bool = False
    max_content_length: int = 1024
    truncation_marker: str = "...[TRUNCATED]"
    log_requests: bool = True
    log_responses: bool = True
    log_notifications: bool = True
    log_errors: bool = True
    pretty_print: bool = False
