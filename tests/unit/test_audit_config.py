"""Tests for audit configuration parsing."""

import logging
import tempfile
from pathlib import Path

import pytest
import yaml

from mcp_remixer.audit.config import AuditConfig
from mcp_remixer.config import load_config


class TestAuditConfigDataclass:
    """Tests for AuditConfig dataclass defaults."""

    def test_defaults(self):
        """Default values should be correct."""
        config = AuditConfig()
        assert config.enabled is False
        assert config.log_file is None
        assert config.truncate is False
        assert config.max_content_length == 1024
        assert config.truncation_marker == "...[TRUNCATED]"
        assert config.log_requests is True
        assert config.log_responses is True
        assert config.log_notifications is True
        assert config.log_errors is True
        assert config.pretty_print is False


class TestAuditConfigParsing:
    """Tests for audit config YAML parsing."""

    def test_empty_audit_section(self, tmp_path):
        """Empty audit section should use defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("audit: {}")

        config = load_config(config_file)
        assert config.audit.enabled is False
        assert config.audit.truncate is False
        assert config.audit.max_content_length == 1024

    def test_no_audit_section(self, tmp_path):
        """Missing audit section should use defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("upstreams: {}")

        config = load_config(config_file)
        assert config.audit.enabled is False

    def test_enabled_true(self, tmp_path):
        """enabled: true should be parsed."""
        config_file = tmp_path / "config.yaml"
        log_file = tmp_path / "audit.jsonl"
        config_file.write_text(f"""
audit:
  enabled: true
  log_file: {log_file}
""")

        config = load_config(config_file)
        assert config.audit.enabled is True
        assert config.audit.log_file == log_file

    def test_truncate_defaults_to_false(self, tmp_path):
        """truncate should default to false."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
""")

        config = load_config(config_file)
        assert config.audit.truncate is False

    def test_truncate_true(self, tmp_path):
        """truncate: true should be parsed."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
  truncate: true
""")

        config = load_config(config_file)
        assert config.audit.truncate is True

    def test_max_content_length_defaults_to_1024(self, tmp_path):
        """max_content_length should default to 1024."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
  truncate: true
""")

        config = load_config(config_file)
        assert config.audit.max_content_length == 1024

    def test_custom_max_content_length(self, tmp_path):
        """Custom max_content_length should be parsed."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
  truncate: true
  max_content_length: 4096
""")

        config = load_config(config_file)
        assert config.audit.max_content_length == 4096

    def test_warning_when_max_content_length_set_but_truncate_false(
        self, tmp_path, caplog
    ):
        """Should warn when max_content_length set but truncate is false."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
  truncate: false
  max_content_length: 4096
""")

        with caplog.at_level(logging.WARNING):
            config = load_config(config_file)

        assert "max_content_length will be ignored" in caplog.text

    def test_no_warning_when_truncate_true_with_max_content_length(
        self, tmp_path, caplog
    ):
        """No warning when truncate is true with max_content_length."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
  truncate: true
  max_content_length: 4096
""")

        with caplog.at_level(logging.WARNING):
            config = load_config(config_file)

        assert "max_content_length will be ignored" not in caplog.text

    def test_no_warning_when_truncate_false_without_max_content_length(
        self, tmp_path, caplog
    ):
        """No warning when truncate is false and max_content_length not set."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
  truncate: false
""")

        with caplog.at_level(logging.WARNING):
            config = load_config(config_file)

        assert "max_content_length will be ignored" not in caplog.text

    def test_relative_log_file_resolved(self, tmp_path):
        """Relative log_file path should be resolved against config dir."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: ./logs/audit.jsonl
""")

        config = load_config(config_file)
        expected = (tmp_path / "logs" / "audit.jsonl").resolve()
        assert config.audit.log_file == expected

    def test_absolute_log_file_resolved(self, tmp_path):
        """Absolute log_file path should be resolved (symlinks expanded)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /var/log/audit.jsonl
""")

        config = load_config(config_file)
        # Path is resolved, which may expand symlinks (e.g., /var -> /private/var on macOS)
        expected = Path("/var/log/audit.jsonl").resolve()
        assert config.audit.log_file == expected

    def test_warning_when_enabled_without_log_file(self, tmp_path, caplog):
        """Should warn when enabled but no log_file specified."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
""")

        with caplog.at_level(logging.WARNING):
            config = load_config(config_file)

        assert "log_file is not set" in caplog.text

    def test_all_options_parsed(self, tmp_path):
        """All audit options should be parsed correctly."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: /tmp/audit.jsonl
  truncate: true
  max_content_length: 2048
  truncation_marker: "[...]"
  log_requests: false
  log_responses: true
  log_notifications: false
  log_errors: true
  pretty_print: true
""")

        config = load_config(config_file)
        assert config.audit.enabled is True
        assert config.audit.truncate is True
        assert config.audit.max_content_length == 2048
        assert config.audit.truncation_marker == "[...]"
        assert config.audit.log_requests is False
        assert config.audit.log_responses is True
        assert config.audit.log_notifications is False
        assert config.audit.log_errors is True
        assert config.audit.pretty_print is True

    def test_env_var_expansion_in_log_file(self, tmp_path, monkeypatch):
        """Environment variables should be expanded in log_file."""
        monkeypatch.setenv("AUDIT_LOG_DIR", "/var/log/mcp")
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
audit:
  enabled: true
  log_file: ${AUDIT_LOG_DIR}/audit.jsonl
""")

        config = load_config(config_file)
        # Path is resolved, which may expand symlinks
        expected = Path("/var/log/mcp/audit.jsonl").resolve()
        assert config.audit.log_file == expected
