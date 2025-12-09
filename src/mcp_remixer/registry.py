"""Tool registry for managing tool names, prefixes, and routing."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from mcp.types import CallToolResult, TextContent, Tool

from mcp_remixer.config import HiddenConfig, UpstreamConfig
from mcp_remixer.exceptions import ToolError, ToolHiddenError, ToolNotFoundError

if TYPE_CHECKING:
    from mcp_remixer.upstream import UpstreamClient, UpstreamManager

logger = logging.getLogger(__name__)


@dataclass
class RegisteredTool:
    """A tool registered in the registry."""

    exposed_name: str  # Name exposed to clients
    original_name: str  # Original tool name
    description: str
    input_schema: dict[str, Any]
    source: str  # "upstream:<name>" or "custom"
    upstream_name: str | None = None  # For upstream tools
    custom_function: Callable | None = None  # For custom tools
    is_async: bool = True


class ToolRegistry:
    """Registry for managing tools from upstreams and custom tools."""

    def __init__(
        self,
        hidden_config: HiddenConfig,
        upstream_manager: UpstreamManager,
    ) -> None:
        self._hidden = hidden_config
        self._upstream_manager = upstream_manager
        self._tools: dict[str, RegisteredTool] = {}
        self._upstream_client: UpstreamClient | None = None

    def set_upstream_client(self, client: UpstreamClient) -> None:
        """Set the upstream client for custom tools to use."""
        self._upstream_client = client

    def _is_hidden(self, tool_name: str, upstream_name: str | None = None) -> bool:
        """Check if a tool should be hidden."""
        for hidden in self._hidden.tools:
            # Check for exact match with upstream prefix
            if upstream_name and hidden == f"{upstream_name}.{tool_name}":
                return True
            # Check for plain name match (hides from all upstreams)
            if hidden == tool_name:
                return True
        return False

    def _apply_prefix(self, tool_name: str, config: UpstreamConfig) -> str:
        """Apply explicit prefix from config."""
        if config.tool_prefix:
            return f"{config.tool_prefix}{tool_name}"
        return tool_name

    def register_upstream_tools(
        self,
        upstream_name: str,
        tools: list[Tool],
        config: UpstreamConfig,
    ) -> None:
        """Register tools from an upstream server.

        Args:
            upstream_name: Name of the upstream
            tools: List of tools from the upstream
            config: Upstream configuration
        """
        for tool in tools:
            # Check if hidden
            if self._is_hidden(tool.name, upstream_name):
                logger.debug(f"Hiding tool '{tool.name}' from upstream '{upstream_name}'")
                continue

            # Apply explicit prefix
            exposed_name = self._apply_prefix(tool.name, config)

            # Store with upstream qualifier for collision detection
            self._tools[f"__pending__{upstream_name}.{exposed_name}"] = RegisteredTool(
                exposed_name=exposed_name,
                original_name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema,
                source=f"upstream:{upstream_name}",
                upstream_name=upstream_name,
            )

    def register_custom_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        function: Callable,
        is_async: bool = True,
    ) -> None:
        """Register a custom tool.

        Args:
            name: Tool name
            description: Tool description
            input_schema: JSON Schema for parameters
            function: The tool function
            is_async: Whether the function is async
        """
        # Check if hidden
        if self._is_hidden(name):
            logger.debug(f"Hiding custom tool '{name}'")
            return

        if name in self._tools:
            logger.warning(f"Custom tool '{name}' overwrites existing tool")

        self._tools[name] = RegisteredTool(
            exposed_name=name,
            original_name=name,
            description=description,
            input_schema=input_schema,
            source="custom",
            custom_function=function,
            is_async=is_async,
        )

    def resolve_collisions(self) -> None:
        """Resolve tool name collisions and finalize the registry.

        This should be called after all upstream and custom tools are registered.
        It handles auto-prefixing when tools from different upstreams have the same name.
        """
        # Group pending tools by exposed name
        pending_by_name: dict[str, list[tuple[str, RegisteredTool]]] = {}

        pending_keys = [k for k in self._tools.keys() if k.startswith("__pending__")]

        for key in pending_keys:
            tool = self._tools[key]
            if tool.exposed_name not in pending_by_name:
                pending_by_name[tool.exposed_name] = []
            pending_by_name[tool.exposed_name].append((key, tool))

        # Process each group
        for exposed_name, tools in pending_by_name.items():
            # Check for collision with custom tools
            has_custom = exposed_name in self._tools and not self._tools[exposed_name].upstream_name

            if len(tools) == 1 and not has_custom:
                # No collision - use the name as-is
                key, tool = tools[0]
                del self._tools[key]
                self._tools[exposed_name] = tool
            else:
                # Collision - auto-prefix with upstream name
                if has_custom:
                    logger.warning(
                        f"Tool '{exposed_name}' from upstream(s) collides with custom tool, "
                        f"upstream tools will be prefixed"
                    )
                else:
                    colliding_upstreams = [t.upstream_name for _, t in tools]
                    logger.warning(
                        f"Tool '{exposed_name}' exists in multiple upstreams "
                        f"{colliding_upstreams}, auto-prefixing with upstream name"
                    )

                for key, tool in tools:
                    del self._tools[key]
                    # Create new name with upstream prefix
                    new_name = f"{tool.upstream_name}.{tool.exposed_name}"
                    tool.exposed_name = new_name
                    self._tools[new_name] = tool

    def list_tools(self) -> list[Tool]:
        """List all registered tools as MCP Tool objects."""
        result = []
        for tool in self._tools.values():
            result.append(
                Tool(
                    name=tool.exposed_name,
                    description=tool.description,
                    inputSchema=tool.input_schema,
                )
            )
        return result

    def get_tool(self, name: str) -> RegisteredTool | None:
        """Get a tool by its exposed name."""
        return self._tools.get(name)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Call a tool by its exposed name.

        Args:
            name: Tool name (exposed name)
            arguments: Tool arguments

        Returns:
            Tool call result

        Raises:
            ToolNotFoundError: If the tool doesn't exist
            ToolHiddenError: If the tool is hidden
        """
        tool = self._tools.get(name)

        if tool is None:
            raise ToolNotFoundError(f"Tool '{name}' not found")

        if tool.source == "custom":
            # Call custom tool
            return await self._call_custom_tool(tool, arguments)
        else:
            # Call upstream tool
            if tool.upstream_name is None:
                raise ToolNotFoundError(f"Tool '{name}' has no upstream")

            return await self._upstream_manager.call_upstream_tool(
                tool.upstream_name,
                tool.original_name,
                arguments,
            )

    async def _call_custom_tool(
        self, tool: RegisteredTool, arguments: dict[str, Any]
    ) -> CallToolResult:
        """Call a custom tool function."""
        if tool.custom_function is None:
            raise ToolNotFoundError(f"Custom tool '{tool.exposed_name}' has no function")

        try:
            # Check if the function expects an upstream client
            import inspect

            sig = inspect.signature(tool.custom_function)
            kwargs = dict(arguments)

            if "upstream" in sig.parameters and self._upstream_client:
                kwargs["upstream"] = self._upstream_client

            # Call the function
            if tool.is_async:
                result = await tool.custom_function(**kwargs)
            else:
                # Run sync function in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, lambda: tool.custom_function(**kwargs)
                )

            # Convert result to CallToolResult
            return self._convert_result(result)

        except ToolError as e:
            # Re-raise ToolError as-is
            return CallToolResult(
                content=[TextContent(type="text", text=f"Error: {e.code}: {e.message}")],
                isError=True,
            )
        except Exception as e:
            logger.exception(f"Error calling custom tool '{tool.exposed_name}'")
            return CallToolResult(
                content=[TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")],
                isError=True,
            )

    def _convert_result(self, result: Any) -> CallToolResult:
        """Convert a custom tool result to CallToolResult."""
        import json

        if isinstance(result, CallToolResult):
            return result

        if isinstance(result, str):
            return CallToolResult(content=[TextContent(type="text", text=result)])

        if isinstance(result, dict):
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        if isinstance(result, list):
            # Assume it's a list of content items
            return CallToolResult(content=result)

        # Default: convert to string
        return CallToolResult(content=[TextContent(type="text", text=str(result))])
