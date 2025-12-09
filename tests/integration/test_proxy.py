"""Integration tests for the proxy server."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import Tool, CallToolResult, TextContent

from mcp_remixer.config import load_config, Config, HiddenConfig, StdioUpstreamConfig
from mcp_remixer.server import MCPRemixerServer
from mcp_remixer.registry import ToolRegistry
from mcp_remixer.upstream import UpstreamManager


@pytest.fixture
def mock_upstream_tools() -> list[Tool]:
    """Tools that would come from an upstream server."""
    return [
        Tool(
            name="read_file",
            description="Read a file",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="write_file",
            description="Write a file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
    ]


@pytest.fixture
def config_with_custom_tools(tmp_path: Path) -> tuple[Config, Path]:
    """Create a config with custom tools."""
    # Create custom tool module
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    tool_file = tools_dir / "custom.py"
    tool_file.write_text("""
from mcp_remixer import tool

@tool(description="Convert text to uppercase")
async def uppercase(text: str):
    return text.upper()

@tool(description="Process and forward to upstream")
async def process_and_save(text: str, path: str, upstream):
    processed = text.strip().upper()
    result = await upstream.call_tool("write_file", {
        "path": path,
        "content": processed
    })
    return f"Saved processed text to {path}"
""")

    config = Config(
        upstreams={
            "filesystem": StdioUpstreamConfig(
                name="filesystem",
                transport="stdio",
                command="echo",
                args=["test"],
            )
        },
        hidden=HiddenConfig(tools=["write_file"]),
        custom_tools=[tool_file],
        config_dir=tmp_path,
    )

    return config, tool_file


class TestToolRegistryIntegration:
    """Integration tests for tool registry with custom tools."""

    @pytest.mark.asyncio
    async def test_custom_tool_calls_upstream(
        self,
        config_with_custom_tools: tuple[Config, Path],
        mock_upstream_tools: list[Tool],
    ):
        """Custom tool can call upstream tools."""
        config, tool_file = config_with_custom_tools

        # Set up mock upstream manager
        manager = UpstreamManager()
        registry = ToolRegistry(config.hidden, manager)

        # Register upstream tools (simulating connected upstream)
        registry.register_upstream_tools(
            "filesystem",
            mock_upstream_tools,
            config.upstreams["filesystem"],
        )

        # Load custom tools
        from mcp_remixer.loader import load_custom_tools
        custom_tools = load_custom_tools(config.custom_tools)

        for tool_def in custom_tools.values():
            registry.register_custom_tool(
                name=tool_def.name,
                description=tool_def.description,
                input_schema=tool_def.parameters,
                function=tool_def.function,
                is_async=tool_def.is_async,
            )

        registry.resolve_collisions()

        # Set up mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = CallToolResult(
            content=[TextContent(type="text", text="Written successfully")]
        )
        registry.set_upstream_client(mock_client)

        # Call the custom tool that chains to upstream
        result = await registry.call_tool("process_and_save", {
            "text": "  hello world  ",
            "path": "/test.txt",
        })

        # Verify upstream was called
        mock_client.call_tool.assert_called_once_with(
            "write_file",
            {"path": "/test.txt", "content": "HELLO WORLD"},
        )

        assert "Saved processed text" in result.content[0].text

    @pytest.mark.asyncio
    async def test_hidden_tools_not_visible(
        self,
        config_with_custom_tools: tuple[Config, Path],
        mock_upstream_tools: list[Tool],
    ):
        """Hidden tools are not exposed."""
        config, tool_file = config_with_custom_tools

        manager = UpstreamManager()
        registry = ToolRegistry(config.hidden, manager)

        # Register upstream tools
        registry.register_upstream_tools(
            "filesystem",
            mock_upstream_tools,
            config.upstreams["filesystem"],
        )

        registry.resolve_collisions()

        # List tools
        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        # write_file should be hidden
        assert "write_file" not in tool_names
        # read_file should be visible
        assert "read_file" in tool_names


class TestConfigIntegration:
    """Integration tests for configuration loading."""

    def test_full_config_loading(self, tmp_path: Path):
        """Loads a complete configuration file."""
        # Create .env file
        env_file = tmp_path / ".env"
        env_file.write_text("API_TOKEN=secret123\n")

        # Create tools directory and file
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "my_tools.py"
        tool_file.write_text("""
from mcp_remixer import tool

@tool(description="Test tool")
async def test_tool():
    pass
""")

        # Create config file
        config_content = """
upstreams:
  filesystem:
    transport: stdio
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/tmp"
    required: true
    tool_prefix: "fs_"

  remote:
    transport: sse
    url: http://localhost:8080/mcp
    headers:
      Authorization: Bearer ${API_TOKEN}

hidden:
  tools:
    - dangerous_tool
    - filesystem.internal_op

custom_tools:
  - ./tools/my_tools.py
"""
        config_path = tmp_path / "mcp-remixer.yaml"
        config_path.write_text(config_content)

        # Load the config
        config = load_config(config_path)

        # Verify upstreams
        assert "filesystem" in config.upstreams
        assert "remote" in config.upstreams

        fs_config = config.upstreams["filesystem"]
        assert fs_config.command == "npx"
        assert fs_config.required is True
        assert fs_config.tool_prefix == "fs_"

        remote_config = config.upstreams["remote"]
        # Env var should be expanded
        assert remote_config.headers["Authorization"] == "Bearer secret123"

        # Verify hidden
        assert "dangerous_tool" in config.hidden.tools

        # Verify custom tools path resolved
        assert len(config.custom_tools) == 1
        assert config.custom_tools[0] == tools_dir / "my_tools.py"


class TestToolNamingIntegration:
    """Integration tests for tool naming and collision resolution."""

    def test_collision_resolution(self):
        """Tests full collision resolution flow."""
        manager = UpstreamManager()
        registry = ToolRegistry(HiddenConfig(), manager)

        # Tools from server_a
        tools_a = [
            Tool(name="search", description="Search A", inputSchema={}),
            Tool(name="unique_a", description="Unique A", inputSchema={}),
        ]

        # Tools from server_b
        tools_b = [
            Tool(name="search", description="Search B", inputSchema={}),
            Tool(name="unique_b", description="Unique B", inputSchema={}),
        ]

        config_a = StdioUpstreamConfig(
            name="server_a",
            transport="stdio",
            command="echo",
        )
        config_b = StdioUpstreamConfig(
            name="server_b",
            transport="stdio",
            command="echo",
        )

        registry.register_upstream_tools("server_a", tools_a, config_a)
        registry.register_upstream_tools("server_b", tools_b, config_b)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        # Colliding 'search' should be prefixed
        assert "server_a.search" in tool_names
        assert "server_b.search" in tool_names
        assert "search" not in tool_names

        # Unique tools should not be prefixed
        assert "unique_a" in tool_names
        assert "unique_b" in tool_names

    def test_explicit_prefix_avoids_collision(self):
        """Explicit prefix prevents collision."""
        manager = UpstreamManager()
        registry = ToolRegistry(HiddenConfig(), manager)

        # Both have 'search' but different prefixes
        tools_a = [Tool(name="search", description="Search A", inputSchema={})]
        tools_b = [Tool(name="search", description="Search B", inputSchema={})]

        config_a = StdioUpstreamConfig(
            name="server_a",
            transport="stdio",
            command="echo",
            tool_prefix="a_",
        )
        config_b = StdioUpstreamConfig(
            name="server_b",
            transport="stdio",
            command="echo",
            tool_prefix="b_",
        )

        registry.register_upstream_tools("server_a", tools_a, config_a)
        registry.register_upstream_tools("server_b", tools_b, config_b)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        # Should use explicit prefixes, not auto-prefix
        assert "a_search" in tool_names
        assert "b_search" in tool_names
        assert "server_a.a_search" not in tool_names
