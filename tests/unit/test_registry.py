"""Tests for tool registry."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mcp.types import Tool, CallToolResult, TextContent

from mcp_remixer.config import HiddenConfig, StdioUpstreamConfig
from mcp_remixer.registry import ToolRegistry, RegisteredTool
from mcp_remixer.upstream import UpstreamManager


@pytest.fixture
def upstream_manager() -> UpstreamManager:
    """Create an upstream manager for testing."""
    return UpstreamManager()


@pytest.fixture
def hidden_config() -> HiddenConfig:
    """Create a hidden config for testing."""
    return HiddenConfig(tools=["dangerous_tool", "filesystem.internal_tool"])


@pytest.fixture
def registry(hidden_config: HiddenConfig, upstream_manager: UpstreamManager) -> ToolRegistry:
    """Create a tool registry for testing."""
    return ToolRegistry(hidden_config, upstream_manager)


@pytest.fixture
def sample_upstream_config() -> StdioUpstreamConfig:
    """Sample upstream configuration."""
    return StdioUpstreamConfig(
        name="filesystem",
        transport="stdio",
        command="echo",
        args=[],
        tool_prefix="",
    )


class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_register_upstream_tools(
        self,
        registry: ToolRegistry,
        sample_tools: list[Tool],
        sample_upstream_config: StdioUpstreamConfig,
    ):
        """Registers tools from an upstream server."""
        registry.register_upstream_tools("filesystem", sample_tools, sample_upstream_config)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        assert "read_file" in tool_names
        assert "write_file" in tool_names

    def test_hidden_tools_filtered(
        self,
        registry: ToolRegistry,
        sample_tools: list[Tool],
        sample_upstream_config: StdioUpstreamConfig,
    ):
        """Hidden tools are not registered."""
        registry.register_upstream_tools("filesystem", sample_tools, sample_upstream_config)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        assert "dangerous_tool" not in tool_names

    def test_hidden_with_upstream_prefix(
        self,
        upstream_manager: UpstreamManager,
        sample_tools: list[Tool],
    ):
        """Hides tools by upstream.tool_name pattern."""
        # Create registry with specific hidden tool
        hidden = HiddenConfig(tools=["filesystem.read_file"])
        registry = ToolRegistry(hidden, upstream_manager)

        config = StdioUpstreamConfig(
            name="filesystem",
            transport="stdio",
            command="echo",
            tool_prefix="",
        )

        registry.register_upstream_tools("filesystem", sample_tools, config)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        assert "read_file" not in tool_names
        assert "write_file" in tool_names

    def test_explicit_prefix_applied(
        self,
        registry: ToolRegistry,
        sample_tools: list[Tool],
    ):
        """Applies explicit tool_prefix from config."""
        config = StdioUpstreamConfig(
            name="filesystem",
            transport="stdio",
            command="echo",
            tool_prefix="fs_",
        )

        registry.register_upstream_tools("filesystem", sample_tools, config)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        assert "fs_read_file" in tool_names
        assert "fs_write_file" in tool_names
        assert "read_file" not in tool_names

    def test_auto_prefix_on_collision(self, upstream_manager: UpstreamManager):
        """Auto-prefixes tools when names collide."""
        registry = ToolRegistry(HiddenConfig(), upstream_manager)

        tool1 = Tool(name="search", description="Search 1", inputSchema={})
        tool2 = Tool(name="search", description="Search 2", inputSchema={})

        config1 = StdioUpstreamConfig(
            name="server_a",
            transport="stdio",
            command="echo",
        )
        config2 = StdioUpstreamConfig(
            name="server_b",
            transport="stdio",
            command="echo",
        )

        registry.register_upstream_tools("server_a", [tool1], config1)
        registry.register_upstream_tools("server_b", [tool2], config2)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        assert "server_a.search" in tool_names
        assert "server_b.search" in tool_names
        assert "search" not in tool_names

    def test_no_collision_no_prefix(self, upstream_manager: UpstreamManager):
        """No prefix when tool name is unique."""
        registry = ToolRegistry(HiddenConfig(), upstream_manager)

        tool1 = Tool(name="read_file", description="Read", inputSchema={})
        tool2 = Tool(name="query", description="Query", inputSchema={})

        config1 = StdioUpstreamConfig(name="filesystem", transport="stdio", command="echo")
        config2 = StdioUpstreamConfig(name="database", transport="stdio", command="echo")

        registry.register_upstream_tools("filesystem", [tool1], config1)
        registry.register_upstream_tools("database", [tool2], config2)
        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        # No collision, so no prefix
        assert "read_file" in tool_names
        assert "query" in tool_names

    def test_custom_tool_registration(self, registry: ToolRegistry):
        """Registers custom tools."""
        async def my_tool(text: str):
            return text.upper()

        registry.register_custom_tool(
            name="uppercase",
            description="Convert to uppercase",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            function=my_tool,
            is_async=True,
        )

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        assert "uppercase" in tool_names

    def test_custom_tool_overrides_upstream(
        self,
        registry: ToolRegistry,
        sample_tools: list[Tool],
        sample_upstream_config: StdioUpstreamConfig,
    ):
        """Custom tools with same name override upstream tools (with auto-prefix)."""
        # Register upstream tools first
        registry.register_upstream_tools("filesystem", sample_tools, sample_upstream_config)

        # Register custom tool with same name
        async def custom_read():
            return "custom"

        registry.register_custom_tool(
            name="read_file",
            description="Custom read",
            input_schema={},
            function=custom_read,
        )

        registry.resolve_collisions()

        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        # Custom tool keeps the name, upstream gets prefixed
        assert "read_file" in tool_names
        assert "filesystem.read_file" in tool_names

        # Verify custom tool is the one without prefix
        custom = registry.get_tool("read_file")
        assert custom is not None
        assert custom.source == "custom"

    def test_get_tool(self, registry: ToolRegistry):
        """Gets a tool by name."""
        async def my_tool():
            pass

        registry.register_custom_tool(
            name="test_tool",
            description="Test",
            input_schema={},
            function=my_tool,
        )

        tool = registry.get_tool("test_tool")

        assert tool is not None
        assert tool.exposed_name == "test_tool"
        assert tool.source == "custom"

    def test_get_nonexistent_tool(self, registry: ToolRegistry):
        """Returns None for nonexistent tool."""
        tool = registry.get_tool("nonexistent")
        assert tool is None


class TestToolRegistryCallTool:
    """Tests for calling tools through the registry."""

    @pytest.mark.asyncio
    async def test_call_custom_tool(self, registry: ToolRegistry):
        """Calls a custom tool and returns result."""
        async def my_tool(text: str):
            return text.upper()

        registry.register_custom_tool(
            name="uppercase",
            description="Convert to uppercase",
            input_schema={},
            function=my_tool,
        )

        result = await registry.call_tool("uppercase", {"text": "hello"})

        assert result.content[0].text == "HELLO"

    @pytest.mark.asyncio
    async def test_call_sync_custom_tool(self, registry: ToolRegistry):
        """Calls a sync custom tool."""
        def my_tool(a: int, b: int):
            return a + b

        registry.register_custom_tool(
            name="add",
            description="Add numbers",
            input_schema={},
            function=my_tool,
            is_async=False,
        )

        result = await registry.call_tool("add", {"a": 2, "b": 3})

        assert result.content[0].text == "5"

    @pytest.mark.asyncio
    async def test_call_tool_returns_dict(self, registry: ToolRegistry):
        """Custom tool returning dict is JSON serialized."""
        async def my_tool():
            return {"status": "ok", "count": 42}

        registry.register_custom_tool(
            name="status",
            description="Get status",
            input_schema={},
            function=my_tool,
        )

        result = await registry.call_tool("status", {})

        assert "status" in result.content[0].text
        assert "ok" in result.content[0].text

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool_raises(self, registry: ToolRegistry):
        """Raises error for nonexistent tool."""
        from mcp_remixer.exceptions import ToolNotFoundError

        with pytest.raises(ToolNotFoundError):
            await registry.call_tool("nonexistent", {})

    @pytest.mark.asyncio
    async def test_call_tool_with_exception(self, registry: ToolRegistry):
        """Handles exceptions in custom tools gracefully."""
        async def bad_tool():
            raise ValueError("Something went wrong")

        registry.register_custom_tool(
            name="bad",
            description="Bad tool",
            input_schema={},
            function=bad_tool,
        )

        result = await registry.call_tool("bad", {})

        assert result.isError is True
        assert "ValueError" in result.content[0].text
        assert "Something went wrong" in result.content[0].text

    @pytest.mark.asyncio
    async def test_call_tool_with_tool_error(self, registry: ToolRegistry):
        """Handles ToolError in custom tools."""
        from mcp_remixer.exceptions import ToolError

        async def tool_with_error():
            raise ToolError("INVALID_INPUT", "Bad input provided")

        registry.register_custom_tool(
            name="validate",
            description="Validate",
            input_schema={},
            function=tool_with_error,
        )

        result = await registry.call_tool("validate", {})

        assert result.isError is True
        assert "INVALID_INPUT" in result.content[0].text
        assert "Bad input provided" in result.content[0].text

    @pytest.mark.asyncio
    async def test_call_tool_with_upstream_client(self, registry: ToolRegistry):
        """Injects upstream client into custom tools."""
        received_upstream = None

        async def my_tool(text: str, upstream):
            nonlocal received_upstream
            received_upstream = upstream
            return "done"

        registry.register_custom_tool(
            name="test",
            description="Test",
            input_schema={},
            function=my_tool,
        )

        # Set up a mock upstream client
        mock_client = MagicMock()
        registry.set_upstream_client(mock_client)

        await registry.call_tool("test", {"text": "hello"})

        assert received_upstream is mock_client
