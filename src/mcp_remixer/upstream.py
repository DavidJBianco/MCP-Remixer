"""Upstream server connection management."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, Tool

from mcp_remixer.config import (
    HTTPUpstreamConfig,
    SSEUpstreamConfig,
    StdioUpstreamConfig,
    UpstreamConfig,
)
from mcp_remixer.exceptions import ToolHiddenError, ToolNotFoundError, UpstreamError

if TYPE_CHECKING:
    from mcp_remixer.registry import ToolRegistry

logger = logging.getLogger(__name__)


class UpstreamClient(Protocol):
    """Interface for calling upstream tools from custom tools.

    This is injected into custom tool functions that declare an
    `upstream: UpstreamClient` parameter.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Call a tool by name.

        Args:
            name: Tool name (can be prefixed like "filesystem.read_file" or plain)
            arguments: Tool arguments

        Returns:
            The tool call result

        Raises:
            ToolNotFoundError: If the tool doesn't exist
            ToolHiddenError: If the tool is hidden
            UpstreamError: If the upstream call fails
        """
        ...

    async def list_tools(self) -> list[Tool]:
        """List all available tools (excluding hidden ones)."""
        ...


@dataclass
class UpstreamConnection:
    """Represents a connection to a single upstream MCP server."""

    name: str
    config: UpstreamConfig
    session: ClientSession | None = None
    tools: list[Tool] | None = None
    _read_stream: Any = None
    _write_stream: Any = None
    _cm: Any = None  # Context manager for the connection
    _httpx_client: Any = None  # Custom httpx client (for SSL bypass)

    @property
    def connected(self) -> bool:
        """Check if the connection is established."""
        return self.session is not None


class UpstreamManager:
    """Manages connections to upstream MCP servers."""

    def __init__(self) -> None:
        self._connections: dict[str, UpstreamConnection] = {}
        self._registry: ToolRegistry | None = None

    def set_registry(self, registry: ToolRegistry) -> None:
        """Set the tool registry for name resolution."""
        self._registry = registry

    @property
    def connections(self) -> dict[str, UpstreamConnection]:
        """Get all connections."""
        return self._connections

    async def connect_upstream(self, config: UpstreamConfig) -> UpstreamConnection:
        """Connect to a single upstream server.

        Args:
            config: Upstream configuration

        Returns:
            UpstreamConnection object

        Raises:
            UpstreamError: If connection fails
        """
        conn = UpstreamConnection(name=config.name, config=config)
        logger.debug(f"Attempting to connect to upstream '{config.name}' (transport: {config.transport})")

        try:
            if isinstance(config, StdioUpstreamConfig):
                await self._connect_stdio(conn, config)
            elif isinstance(config, SSEUpstreamConfig):
                await self._connect_sse(conn, config)
            elif isinstance(config, HTTPUpstreamConfig):
                await self._connect_http(conn, config)
            else:
                raise UpstreamError(f"Unknown transport type for upstream '{config.name}'")

            # Fetch tools from the upstream
            if conn.session:
                result = await conn.session.list_tools()
                conn.tools = list(result.tools)
                logger.info(
                    f"Connected to upstream '{config.name}' with {len(conn.tools)} tools"
                )

        except BaseException as e:
            logger.error(f"Failed to connect to upstream '{config.name}': {type(e).__name__}: {e}")
            # Re-raise CancelledError and other BaseExceptions that shouldn't be suppressed
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            if config.required:
                raise UpstreamError(f"Failed to connect to required upstream '{config.name}': {e}")
            logger.warning(f"Continuing without optional upstream '{config.name}'")
            conn.session = None
            conn.tools = []

        self._connections[config.name] = conn
        return conn

    async def _connect_stdio(
        self, conn: UpstreamConnection, config: StdioUpstreamConfig
    ) -> None:
        """Establish a stdio connection to an upstream server."""
        # Merge environment
        env = os.environ.copy()
        env.update(config.env)

        # Create server parameters
        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=env,
        )

        # Create the stdio client
        conn._cm = stdio_client(server_params)
        streams = await conn._cm.__aenter__()
        conn._read_stream, conn._write_stream = streams

        # Create session
        session_cm = ClientSession(conn._read_stream, conn._write_stream)
        conn.session = await session_cm.__aenter__()

        # Initialize the session
        await conn.session.initialize()

    async def _connect_sse(self, conn: UpstreamConnection, config: SSEUpstreamConfig) -> None:
        """Establish an SSE connection to an upstream server."""
        # Create custom httpx client if SSL verification is disabled
        if not config.verify_ssl:
            import httpx
            logger.warning(f"SSL verification disabled for upstream '{config.name}'")
            conn._httpx_client = httpx.AsyncClient(verify=False)

        # Create the SSE client
        conn._cm = sse_client(
            config.url,
            headers=config.headers,
            httpx_client=conn._httpx_client,
        )
        streams = await conn._cm.__aenter__()
        conn._read_stream, conn._write_stream = streams

        # Create session
        session_cm = ClientSession(conn._read_stream, conn._write_stream)
        conn.session = await session_cm.__aenter__()

        # Initialize the session
        await conn.session.initialize()

    async def _connect_http(
        self, conn: UpstreamConnection, config: HTTPUpstreamConfig
    ) -> None:
        """Establish an HTTP connection to an upstream server using Streamable HTTP."""
        logger.debug(f"Connecting to HTTP upstream '{config.name}' at {config.url}")

        # Create custom httpx client if SSL verification is disabled
        if not config.verify_ssl:
            import httpx
            logger.warning(f"SSL verification disabled for upstream '{config.name}'")
            conn._httpx_client = httpx.AsyncClient(verify=False)

        # Create the Streamable HTTP client
        conn._cm = streamablehttp_client(
            config.url,
            headers=config.headers,
            timeout=config.timeout,
            sse_read_timeout=config.read_timeout,
            httpx_client=conn._httpx_client,
        )
        logger.debug(f"Opening HTTP connection to '{config.name}'...")
        streams = await conn._cm.__aenter__()
        # streamablehttp_client returns 3 values: (read_stream, write_stream, get_session_id)
        conn._read_stream, conn._write_stream, _ = streams
        logger.debug(f"HTTP connection established for '{config.name}', creating session...")

        # Create session
        session_cm = ClientSession(conn._read_stream, conn._write_stream)
        conn.session = await session_cm.__aenter__()

        # Initialize the session
        logger.debug(f"Initializing MCP session for '{config.name}'...")
        await conn.session.initialize()
        logger.debug(f"MCP session initialized for '{config.name}'")

    async def connect_all(self, configs: dict[str, UpstreamConfig]) -> None:
        """Connect to all configured upstreams.

        Args:
            configs: Dictionary of upstream configurations

        Raises:
            UpstreamError: If a required upstream fails to connect
        """
        # Connect to all upstreams concurrently
        tasks = [self.connect_upstream(config) for config in configs.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for any exceptions (from required upstreams)
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Upstream connection returned exception: {type(result).__name__}: {result}")
                if isinstance(result, UpstreamError):
                    raise result
                # Re-raise other exceptions as UpstreamError
                raise UpstreamError(f"Upstream connection failed: {result}")

        # Check if all required upstreams connected
        for name, conn in self._connections.items():
            if conn.config.required and not conn.connected:
                raise UpstreamError(f"Required upstream '{name}' failed to connect")

    async def disconnect_all(self) -> None:
        """Disconnect from all upstream servers."""
        for conn in self._connections.values():
            try:
                if conn.session:
                    # Close the session
                    await conn.session.__aexit__(None, None, None)
                if conn._cm:
                    await conn._cm.__aexit__(None, None, None)
                if conn._httpx_client:
                    await conn._httpx_client.aclose()
            except Exception as e:
                logger.warning(f"Error disconnecting from '{conn.name}': {e}")

        self._connections.clear()

    def get_all_upstream_tools(self) -> list[tuple[str, Tool]]:
        """Get all tools from all connected upstreams.

        Returns:
            List of (upstream_name, tool) tuples
        """
        all_tools = []
        for name, conn in self._connections.items():
            if conn.tools:
                for tool in conn.tools:
                    all_tools.append((name, tool))
        return all_tools

    async def call_upstream_tool(
        self, upstream_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        """Call a tool on a specific upstream.

        Args:
            upstream_name: Name of the upstream
            tool_name: Name of the tool (original name, not prefixed)
            arguments: Tool arguments

        Returns:
            Tool call result

        Raises:
            UpstreamError: If the call fails
            ToolNotFoundError: If the upstream doesn't exist
        """
        conn = self._connections.get(upstream_name)
        if not conn or not conn.session:
            raise ToolNotFoundError(f"Upstream '{upstream_name}' not found or not connected")

        try:
            result = await conn.session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            raise UpstreamError(f"Error calling tool '{tool_name}' on '{upstream_name}': {e}")


class UpstreamClientImpl:
    """Implementation of UpstreamClient that routes calls through the registry."""

    def __init__(self, registry: ToolRegistry, manager: UpstreamManager) -> None:
        self._registry = registry
        self._manager = manager

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Call a tool by its exposed name."""
        return await self._registry.call_tool(name, arguments)

    async def list_tools(self) -> list[Tool]:
        """List all available tools."""
        return self._registry.list_tools()


@asynccontextmanager
async def create_upstream_manager(configs: dict[str, UpstreamConfig]):
    """Create and manage upstream connections.

    Usage:
        async with create_upstream_manager(configs) as manager:
            # Use manager
            ...
    """
    manager = UpstreamManager()
    try:
        await manager.connect_all(configs)
        yield manager
    finally:
        await manager.disconnect_all()
