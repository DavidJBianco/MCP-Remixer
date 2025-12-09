"""Integration tests for upstream server connections."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import Tool, ListToolsResult

from mcp_remixer.config import Config, HiddenConfig, StdioUpstreamConfig, HTTPUpstreamConfig
from mcp_remixer.server import MCPRemixerServer
from mcp_remixer.upstream import UpstreamManager


@pytest.fixture
def mock_tools() -> list[Tool]:
    """Sample tools that a mock upstream would return."""
    return [
        Tool(
            name="read_file",
            description="Read a file from the filesystem",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="write_file",
            description="Write a file to the filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="list_directory",
            description="List directory contents",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
    ]


class TestUpstreamToolPassthrough:
    """Tests that verify upstream tools are properly passed through the remixer."""

    @pytest.mark.asyncio
    async def test_upstream_tools_are_registered(self, mock_tools: list[Tool]):
        """Verifies that tools from upstream server are registered in the registry."""
        # Create a mock session that returns our test tools
        mock_session = AsyncMock()
        mock_session.list_tools.return_value = ListToolsResult(tools=mock_tools)
        mock_session.initialize = AsyncMock()

        # Create config
        config = Config(
            upstreams={
                "filesystem": StdioUpstreamConfig(
                    name="filesystem",
                    transport="stdio",
                    command="echo",  # Doesn't matter, we're mocking
                    args=["test"],
                )
            },
            hidden=HiddenConfig(tools=[]),
            custom_tools=[],
            config_dir=Path("."),
        )

        # Patch the stdio_client and ClientSession to return our mock
        with patch("mcp_remixer.upstream.stdio_client") as mock_stdio_client, \
             patch("mcp_remixer.upstream.ClientSession") as mock_client_session:

            # Set up the mock context managers
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
            mock_cm.__aexit__ = AsyncMock()
            mock_stdio_client.return_value = mock_cm

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock()
            mock_client_session.return_value = mock_session_cm

            # Create server and initialize
            server = MCPRemixerServer(config)
            await server.initialize()

            # Verify tools were registered
            tools = server._registry.list_tools()
            tool_names = [t.name for t in tools]

            assert "read_file" in tool_names
            assert "write_file" in tool_names
            assert "list_directory" in tool_names
            assert len(tools) == 3

            # Cleanup
            await server.shutdown()

    @pytest.mark.asyncio
    async def test_hidden_upstream_tools_are_filtered(self, mock_tools: list[Tool]):
        """Verifies that hidden tools from upstream are not exposed."""
        mock_session = AsyncMock()
        mock_session.list_tools.return_value = ListToolsResult(tools=mock_tools)
        mock_session.initialize = AsyncMock()

        # Config that hides write_file
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
            custom_tools=[],
            config_dir=Path("."),
        )

        with patch("mcp_remixer.upstream.stdio_client") as mock_stdio_client, \
             patch("mcp_remixer.upstream.ClientSession") as mock_client_session:

            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
            mock_cm.__aexit__ = AsyncMock()
            mock_stdio_client.return_value = mock_cm

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock()
            mock_client_session.return_value = mock_session_cm

            server = MCPRemixerServer(config)
            await server.initialize()

            tools = server._registry.list_tools()
            tool_names = [t.name for t in tools]

            # write_file should be hidden
            assert "write_file" not in tool_names
            # Others should be visible
            assert "read_file" in tool_names
            assert "list_directory" in tool_names
            assert len(tools) == 2

            await server.shutdown()

    @pytest.mark.asyncio
    async def test_upstream_tools_with_prefix(self, mock_tools: list[Tool]):
        """Verifies that tool_prefix is applied to upstream tools."""
        mock_session = AsyncMock()
        mock_session.list_tools.return_value = ListToolsResult(tools=mock_tools)
        mock_session.initialize = AsyncMock()

        # Config with tool_prefix
        config = Config(
            upstreams={
                "filesystem": StdioUpstreamConfig(
                    name="filesystem",
                    transport="stdio",
                    command="echo",
                    args=["test"],
                    tool_prefix="fs_",
                )
            },
            hidden=HiddenConfig(tools=[]),
            custom_tools=[],
            config_dir=Path("."),
        )

        with patch("mcp_remixer.upstream.stdio_client") as mock_stdio_client, \
             patch("mcp_remixer.upstream.ClientSession") as mock_client_session:

            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
            mock_cm.__aexit__ = AsyncMock()
            mock_stdio_client.return_value = mock_cm

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock()
            mock_client_session.return_value = mock_session_cm

            server = MCPRemixerServer(config)
            await server.initialize()

            tools = server._registry.list_tools()
            tool_names = [t.name for t in tools]

            # All tools should have fs_ prefix
            assert "fs_read_file" in tool_names
            assert "fs_write_file" in tool_names
            assert "fs_list_directory" in tool_names
            # Original names should not exist
            assert "read_file" not in tool_names

            await server.shutdown()

    @pytest.mark.asyncio
    async def test_custom_tools_alongside_upstream(self, mock_tools: list[Tool], tmp_path: Path):
        """Verifies custom tools appear alongside upstream tools."""
        mock_session = AsyncMock()
        mock_session.list_tools.return_value = ListToolsResult(tools=mock_tools)
        mock_session.initialize = AsyncMock()

        # Create a custom tool file
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        tool_file = tools_dir / "custom.py"
        tool_file.write_text("""
from mcp_remixer import tool

@tool(description="A custom greeting tool")
async def say_hello(name: str) -> str:
    return f"Hello, {name}!"
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
            hidden=HiddenConfig(tools=[]),
            custom_tools=[tool_file],
            config_dir=tmp_path,
        )

        with patch("mcp_remixer.upstream.stdio_client") as mock_stdio_client, \
             patch("mcp_remixer.upstream.ClientSession") as mock_client_session:

            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
            mock_cm.__aexit__ = AsyncMock()
            mock_stdio_client.return_value = mock_cm

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock()
            mock_client_session.return_value = mock_session_cm

            server = MCPRemixerServer(config)
            await server.initialize()

            tools = server._registry.list_tools()
            tool_names = [t.name for t in tools]

            # Should have both upstream and custom tools
            assert "read_file" in tool_names
            assert "write_file" in tool_names
            assert "list_directory" in tool_names
            assert "say_hello" in tool_names
            assert len(tools) == 4

            await server.shutdown()

    @pytest.mark.asyncio
    async def test_failed_optional_upstream_doesnt_block(self):
        """Verifies that a failed optional upstream doesn't prevent server start."""
        config = Config(
            upstreams={
                "optional_server": StdioUpstreamConfig(
                    name="optional_server",
                    transport="stdio",
                    command="nonexistent_command",
                    args=[],
                    required=False,  # Optional
                )
            },
            hidden=HiddenConfig(tools=[]),
            custom_tools=[],
            config_dir=Path("."),
        )

        with patch("mcp_remixer.upstream.stdio_client") as mock_stdio_client:
            # Make the connection fail
            mock_stdio_client.side_effect = Exception("Connection failed")

            server = MCPRemixerServer(config)
            # Should not raise even though upstream failed
            await server.initialize()

            # Should have no tools but server should be running
            tools = server._registry.list_tools()
            assert len(tools) == 0

            await server.shutdown()

    @pytest.mark.asyncio
    async def test_failed_required_upstream_raises(self):
        """Verifies that a failed required upstream raises an error."""
        config = Config(
            upstreams={
                "required_server": StdioUpstreamConfig(
                    name="required_server",
                    transport="stdio",
                    command="nonexistent_command",
                    args=[],
                    required=True,  # Required
                )
            },
            hidden=HiddenConfig(tools=[]),
            custom_tools=[],
            config_dir=Path("."),
        )

        with patch("mcp_remixer.upstream.stdio_client") as mock_stdio_client:
            mock_stdio_client.side_effect = Exception("Connection failed")

            server = MCPRemixerServer(config)

            from mcp_remixer.exceptions import UpstreamError
            with pytest.raises(UpstreamError):
                await server.initialize()

    @pytest.mark.asyncio
    async def test_http_upstream_tools_are_registered(self, mock_tools: list[Tool]):
        """Verifies that tools from an HTTP upstream are registered."""
        mock_session = AsyncMock()
        mock_session.list_tools.return_value = ListToolsResult(tools=mock_tools)
        mock_session.initialize = AsyncMock()

        config = Config(
            upstreams={
                "cloud_api": HTTPUpstreamConfig(
                    name="cloud_api",
                    transport="http",
                    url="https://api.example.com/mcp",
                    headers={"Authorization": "Bearer test-token"},
                    timeout=30.0,
                    read_timeout=300.0,
                )
            },
            hidden=HiddenConfig(tools=[]),
            custom_tools=[],
            config_dir=Path("."),
        )

        with patch("mcp_remixer.upstream.streamablehttp_client") as mock_http_client, \
             patch("mcp_remixer.upstream.ClientSession") as mock_client_session:

            # Set up the mock context managers
            mock_cm = AsyncMock()
            # streamablehttp_client returns 3 values: (read_stream, write_stream, get_session_id)
            mock_cm.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock(), lambda: None))
            mock_cm.__aexit__ = AsyncMock()
            mock_http_client.return_value = mock_cm

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock()
            mock_client_session.return_value = mock_session_cm

            server = MCPRemixerServer(config)
            await server.initialize()

            # Verify streamablehttp_client was called with correct args
            # (read_timeout maps to sse_read_timeout in the SDK)
            mock_http_client.assert_called_once_with(
                "https://api.example.com/mcp",
                headers={"Authorization": "Bearer test-token"},
                timeout=30.0,
                sse_read_timeout=300.0,
                httpx_client=None,
            )

            # Verify tools were registered
            tools = server._registry.list_tools()
            tool_names = [t.name for t in tools]

            assert "read_file" in tool_names
            assert "write_file" in tool_names
            assert "list_directory" in tool_names
            assert len(tools) == 3

            await server.shutdown()

    @pytest.mark.asyncio
    async def test_http_upstream_with_verify_ssl_false(self, mock_tools: list[Tool]):
        """Verifies that verify_ssl=False creates a custom httpx client."""
        mock_session = AsyncMock()
        mock_session.list_tools.return_value = ListToolsResult(tools=mock_tools)
        mock_session.initialize = AsyncMock()

        config = Config(
            upstreams={
                "insecure_api": HTTPUpstreamConfig(
                    name="insecure_api",
                    transport="http",
                    url="https://self-signed.example.com/mcp",
                    verify_ssl=False,
                )
            },
            hidden=HiddenConfig(tools=[]),
            custom_tools=[],
            config_dir=Path("."),
        )

        with patch("mcp_remixer.upstream.streamablehttp_client") as mock_http_client, \
             patch("mcp_remixer.upstream.ClientSession") as mock_client_session, \
             patch("httpx.AsyncClient") as mock_httpx_client:

            # Set up the mock context managers
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock(), lambda: None))
            mock_cm.__aexit__ = AsyncMock()
            mock_http_client.return_value = mock_cm

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock()
            mock_client_session.return_value = mock_session_cm

            # Mock the httpx client
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.aclose = AsyncMock()
            mock_httpx_client.return_value = mock_httpx_instance

            server = MCPRemixerServer(config)
            await server.initialize()

            # Verify httpx.AsyncClient was created with verify=False
            mock_httpx_client.assert_called_once_with(verify=False)

            # Verify streamablehttp_client was called with the custom client
            mock_http_client.assert_called_once_with(
                "https://self-signed.example.com/mcp",
                headers={},
                timeout=30.0,
                sse_read_timeout=300.0,
                httpx_client=mock_httpx_instance,
            )

            await server.shutdown()
