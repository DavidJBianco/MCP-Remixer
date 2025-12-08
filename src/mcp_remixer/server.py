"""MCP Proxy Server implementation."""

from __future__ import annotations

import logging
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from mcp_remixer.config import Config, load_config
from mcp_remixer.loader import load_custom_tools
from mcp_remixer.registry import ToolRegistry
from mcp_remixer.upstream import UpstreamClientImpl, UpstreamManager

logger = logging.getLogger(__name__)


class MCPRemixerServer:
    """The main MCP Remixer proxy server."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._server = Server("mcp-remixer")
        self._upstream_manager = UpstreamManager()
        self._registry = ToolRegistry(config.hidden, self._upstream_manager)

        # Set up the MCP server handlers
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Set up MCP server request handlers."""

        @self._server.list_tools()
        async def list_tools() -> list[Tool]:
            return self._registry.list_tools()

        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            result = await self._registry.call_tool(name, arguments or {})
            return result.content

    async def initialize(self) -> None:
        """Initialize the server by connecting to upstreams and loading custom tools."""
        # Connect to upstream servers
        logger.info("Connecting to upstream servers...")
        await self._upstream_manager.connect_all(self._config.upstreams)

        # Register upstream tools
        for name, conn in self._upstream_manager.connections.items():
            if conn.tools:
                self._registry.register_upstream_tools(
                    name, conn.tools, conn.config
                )

        # Load and register custom tools
        logger.info("Loading custom tools...")
        custom_tools = load_custom_tools(self._config.custom_tools)

        for tool_def in custom_tools.values():
            self._registry.register_custom_tool(
                name=tool_def.name,
                description=tool_def.description,
                input_schema=tool_def.parameters,
                function=tool_def.function,
                is_async=tool_def.is_async,
            )

        # Resolve name collisions
        self._registry.resolve_collisions()

        # Set up the upstream client for custom tools
        upstream_client = UpstreamClientImpl(self._registry, self._upstream_manager)
        self._registry.set_upstream_client(upstream_client)
        self._upstream_manager.set_registry(self._registry)

        tool_count = len(self._registry.list_tools())
        logger.info(f"Server initialized with {tool_count} tools")

    async def shutdown(self) -> None:
        """Shut down the server and disconnect from upstreams."""
        logger.info("Shutting down server...")
        await self._upstream_manager.disconnect_all()

    async def run_stdio(self) -> None:
        """Run the server using stdio transport."""
        try:
            await self.initialize()

            logger.info("Starting stdio server...")
            async with stdio_server() as (read_stream, write_stream):
                await self._server.run(
                    read_stream,
                    write_stream,
                    self._server.create_initialization_options(),
                )
        finally:
            await self.shutdown()


async def run_server(config_path: Path) -> None:
    """Run the MCP Remixer server.

    Args:
        config_path: Path to the configuration file
    """
    config = load_config(config_path)
    server = MCPRemixerServer(config)
    await server.run_stdio()
