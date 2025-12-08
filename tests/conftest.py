"""Shared fixtures for mcp-remixer tests."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from mcp.types import CallToolResult, TextContent, Tool

from mcp_remixer.config import (
    Config,
    HiddenConfig,
    StdioUpstreamConfig,
    SSEUpstreamConfig,
)
from mcp_remixer.tool import clear_custom_tools


@pytest.fixture(autouse=True)
def clear_tools():
    """Clear custom tools before each test."""
    clear_custom_tools()
    yield
    clear_custom_tools()


@pytest.fixture
def sample_stdio_config() -> StdioUpstreamConfig:
    """Sample stdio upstream configuration."""
    return StdioUpstreamConfig(
        name="filesystem",
        transport="stdio",
        command="echo",
        args=["hello"],
        required=False,
        tool_prefix="",
    )


@pytest.fixture
def sample_sse_config() -> SSEUpstreamConfig:
    """Sample SSE upstream configuration."""
    return SSEUpstreamConfig(
        name="remote",
        transport="sse",
        url="http://localhost:8080/mcp",
        headers={"Authorization": "Bearer token"},
        required=False,
        tool_prefix="",
    )


@pytest.fixture
def sample_config(tmp_path: Path, sample_stdio_config: StdioUpstreamConfig) -> Config:
    """Sample full configuration."""
    return Config(
        upstreams={"filesystem": sample_stdio_config},
        hidden=HiddenConfig(tools=["dangerous_tool"]),
        custom_tools=[],
        config_dir=tmp_path,
    )


@pytest.fixture
def sample_tools() -> list[Tool]:
    """Sample MCP tools from an upstream server."""
    return [
        Tool(
            name="read_file",
            description="Read a file from the filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="write_file",
            description="Write a file to the filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="dangerous_tool",
            description="A dangerous tool that should be hidden",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@pytest.fixture
def mock_upstream_session() -> AsyncMock:
    """Mock MCP ClientSession for upstream connections."""
    session = AsyncMock()
    session.list_tools.return_value = MagicMock(tools=[])
    session.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text="mock result")]
    )
    return session


@pytest.fixture
def mock_call_tool_result() -> CallToolResult:
    """Sample tool call result."""
    return CallToolResult(
        content=[TextContent(type="text", text="Success")]
    )


@pytest.fixture
def config_yaml_content() -> str:
    """Sample YAML configuration content."""
    return """
upstreams:
  filesystem:
    transport: stdio
    command: echo
    args:
      - hello
    required: true

  remote:
    transport: sse
    url: http://localhost:8080/mcp
    headers:
      Authorization: Bearer secret

hidden:
  tools:
    - dangerous_tool
    - filesystem.internal_tool

custom_tools:
  - ./tools/custom.py
"""


@pytest.fixture
def config_file(tmp_path: Path, config_yaml_content: str) -> Path:
    """Create a temporary config file."""
    config_path = tmp_path / "mcp-remixer.yaml"
    config_path.write_text(config_yaml_content)
    return config_path
