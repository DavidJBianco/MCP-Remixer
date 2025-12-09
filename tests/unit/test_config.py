"""Tests for configuration loading."""

import os
import pytest
from pathlib import Path

from mcp_remixer.config import (
    Config,
    StdioUpstreamConfig,
    SSEUpstreamConfig,
    HTTPUpstreamConfig,
    load_config,
    _expand_env_vars,
)
from mcp_remixer.exceptions import ConfigError


class TestExpandEnvVars:
    """Tests for environment variable expansion."""

    def test_expand_single_var(self, monkeypatch):
        """Expands a single environment variable."""
        monkeypatch.setenv("TEST_VAR", "hello")
        result = _expand_env_vars("${TEST_VAR} world")
        assert result == "hello world"

    def test_expand_multiple_vars(self, monkeypatch):
        """Expands multiple environment variables."""
        monkeypatch.setenv("VAR1", "hello")
        monkeypatch.setenv("VAR2", "world")
        result = _expand_env_vars("${VAR1} ${VAR2}")
        assert result == "hello world"

    def test_missing_var_raises_error(self):
        """Raises error for missing environment variable."""
        # Ensure the var doesn't exist
        os.environ.pop("NONEXISTENT_VAR", None)
        with pytest.raises(ConfigError) as exc_info:
            _expand_env_vars("${NONEXISTENT_VAR}")
        assert "NONEXISTENT_VAR" in str(exc_info.value)

    def test_no_vars_unchanged(self):
        """String without variables is unchanged."""
        result = _expand_env_vars("no variables here")
        assert result == "no variables here"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_valid_config(self, tmp_path: Path):
        """Loads a valid configuration file."""
        config_content = """
upstreams:
  filesystem:
    transport: stdio
    command: echo
    args:
      - hello
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert "filesystem" in config.upstreams
        upstream = config.upstreams["filesystem"]
        assert isinstance(upstream, StdioUpstreamConfig)
        assert upstream.command == "echo"
        assert upstream.args == ["hello"]

    def test_load_sse_upstream(self, tmp_path: Path):
        """Loads an SSE upstream configuration."""
        config_content = """
upstreams:
  remote:
    transport: sse
    url: http://localhost:8080/mcp
    headers:
      Authorization: Bearer token
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert "remote" in config.upstreams
        upstream = config.upstreams["remote"]
        assert isinstance(upstream, SSEUpstreamConfig)
        assert upstream.url == "http://localhost:8080/mcp"
        assert upstream.headers == {"Authorization": "Bearer token"}

    def test_load_hidden_tools(self, tmp_path: Path):
        """Loads hidden tools configuration."""
        config_content = """
upstreams:
  test:
    transport: stdio
    command: echo

hidden:
  tools:
    - dangerous_tool
    - test.internal_tool
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert "dangerous_tool" in config.hidden.tools
        assert "test.internal_tool" in config.hidden.tools

    def test_load_custom_tools_paths(self, tmp_path: Path):
        """Loads custom tool paths and resolves relative paths."""
        config_content = """
upstreams: {}
custom_tools:
  - ./tools/custom.py
  - /absolute/path/tools.py
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert len(config.custom_tools) == 2
        # Relative path should be resolved against config directory
        assert config.custom_tools[0] == tmp_path / "tools" / "custom.py"
        # Absolute path should be unchanged
        assert config.custom_tools[1] == Path("/absolute/path/tools.py")

    def test_missing_config_file_raises_error(self, tmp_path: Path):
        """Raises error for missing configuration file."""
        config_path = tmp_path / "nonexistent.yaml"
        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)
        assert "not found" in str(exc_info.value)

    def test_invalid_yaml_raises_error(self, tmp_path: Path):
        """Raises error for invalid YAML."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("invalid: yaml: content: [")

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)
        assert "Invalid YAML" in str(exc_info.value)

    def test_missing_transport_raises_error(self, tmp_path: Path):
        """Raises error when transport is missing."""
        config_content = """
upstreams:
  test:
    command: echo
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)
        assert "transport" in str(exc_info.value)

    def test_missing_command_for_stdio_raises_error(self, tmp_path: Path):
        """Raises error when stdio transport missing command."""
        config_content = """
upstreams:
  test:
    transport: stdio
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)
        assert "command" in str(exc_info.value)

    def test_missing_url_for_sse_raises_error(self, tmp_path: Path):
        """Raises error when SSE transport missing URL."""
        config_content = """
upstreams:
  test:
    transport: sse
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)
        assert "url" in str(exc_info.value)

    def test_invalid_transport_raises_error(self, tmp_path: Path):
        """Raises error for unknown transport type."""
        config_content = """
upstreams:
  test:
    transport: websocket
    url: ws://localhost
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)
        assert "invalid transport" in str(exc_info.value).lower()

    def test_env_var_expansion_in_config(self, tmp_path: Path, monkeypatch):
        """Expands environment variables in config values."""
        monkeypatch.setenv("TEST_TOKEN", "secret-token")
        config_content = """
upstreams:
  remote:
    transport: sse
    url: http://localhost:8080/mcp
    headers:
      Authorization: Bearer ${TEST_TOKEN}
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        upstream = config.upstreams["remote"]
        assert isinstance(upstream, SSEUpstreamConfig)
        assert upstream.headers["Authorization"] == "Bearer secret-token"

    def test_load_dotenv_file(self, tmp_path: Path):
        """Loads .env file from config directory."""
        # Create .env file
        env_file = tmp_path / ".env"
        env_file.write_text("MY_SECRET=from-dotenv\n")

        config_content = """
upstreams:
  remote:
    transport: sse
    url: http://localhost:8080/mcp
    headers:
      Authorization: Bearer ${MY_SECRET}
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        upstream = config.upstreams["remote"]
        assert isinstance(upstream, SSEUpstreamConfig)
        assert upstream.headers["Authorization"] == "Bearer from-dotenv"

    def test_required_defaults_to_false(self, tmp_path: Path):
        """required field defaults to False."""
        config_content = """
upstreams:
  test:
    transport: stdio
    command: echo
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.upstreams["test"].required is False

    def test_required_can_be_set_true(self, tmp_path: Path):
        """required field can be set to True."""
        config_content = """
upstreams:
  test:
    transport: stdio
    command: echo
    required: true
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.upstreams["test"].required is True

    def test_tool_prefix_defaults_to_empty(self, tmp_path: Path):
        """tool_prefix defaults to empty string."""
        config_content = """
upstreams:
  test:
    transport: stdio
    command: echo
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.upstreams["test"].tool_prefix == ""

    def test_tool_prefix_can_be_set(self, tmp_path: Path):
        """tool_prefix can be configured."""
        config_content = """
upstreams:
  test:
    transport: stdio
    command: echo
    tool_prefix: "fs_"
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert config.upstreams["test"].tool_prefix == "fs_"

    def test_empty_config_is_valid(self, tmp_path: Path):
        """Empty config file is valid (no upstreams)."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")

        config = load_config(config_path)

        assert config.upstreams == {}
        assert config.hidden.tools == []
        assert config.custom_tools == []

    def test_load_http_upstream(self, tmp_path: Path):
        """Loads an HTTP upstream configuration."""
        config_content = """
upstreams:
  cloud:
    transport: http
    url: https://api.example.com/mcp
    headers:
      Authorization: Bearer token
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        assert "cloud" in config.upstreams
        upstream = config.upstreams["cloud"]
        assert isinstance(upstream, HTTPUpstreamConfig)
        assert upstream.url == "https://api.example.com/mcp"
        assert upstream.headers == {"Authorization": "Bearer token"}
        # Check defaults
        assert upstream.timeout == 30.0
        assert upstream.read_timeout == 300.0

    def test_load_http_with_custom_timeouts(self, tmp_path: Path):
        """Loads HTTP config with custom timeout values."""
        config_content = """
upstreams:
  cloud:
    transport: http
    url: https://api.example.com/mcp
    timeout: 60
    read_timeout: 600
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        upstream = config.upstreams["cloud"]
        assert isinstance(upstream, HTTPUpstreamConfig)
        assert upstream.timeout == 60.0
        assert upstream.read_timeout == 600.0

    def test_missing_url_for_http_raises_error(self, tmp_path: Path):
        """Raises error when http transport missing URL."""
        config_content = """
upstreams:
  test:
    transport: http
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)
        assert "url" in str(exc_info.value)

    def test_env_var_expansion_in_http(self, tmp_path: Path, monkeypatch):
        """Expands environment variables in http config."""
        monkeypatch.setenv("API_TOKEN", "secret-token")
        monkeypatch.setenv("API_URL", "https://api.example.com/mcp")
        config_content = """
upstreams:
  cloud:
    transport: http
    url: ${API_URL}
    headers:
      Authorization: Bearer ${API_TOKEN}
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        upstream = config.upstreams["cloud"]
        assert isinstance(upstream, HTTPUpstreamConfig)
        assert upstream.url == "https://api.example.com/mcp"
        assert upstream.headers["Authorization"] == "Bearer secret-token"

    def test_http_verify_ssl_defaults_to_true(self, tmp_path: Path):
        """verify_ssl defaults to True for HTTP upstreams."""
        config_content = """
upstreams:
  cloud:
    transport: http
    url: https://api.example.com/mcp
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        upstream = config.upstreams["cloud"]
        assert isinstance(upstream, HTTPUpstreamConfig)
        assert upstream.verify_ssl is True

    def test_http_verify_ssl_can_be_disabled(self, tmp_path: Path):
        """verify_ssl can be set to false for HTTP upstreams."""
        config_content = """
upstreams:
  insecure:
    transport: http
    url: https://self-signed.example.com/mcp
    verify_ssl: false
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        config = load_config(config_path)

        upstream = config.upstreams["insecure"]
        assert isinstance(upstream, HTTPUpstreamConfig)
        assert upstream.verify_ssl is False
