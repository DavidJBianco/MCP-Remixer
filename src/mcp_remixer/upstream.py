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
    _cm: Any = None  # Context manager for the connection (STDIO only)
    _task: asyncio.Task | None = None  # Background task for HTTP/SSE connections
    _ready_event: asyncio.Event | None = None  # Signals when connection is ready
    _shutdown_event: asyncio.Event | None = None  # Signals when to shutdown
    _error: Exception | None = None  # Stores any error from the connection task

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

    async def _run_http_connection(
        self, conn: UpstreamConnection, config: HTTPUpstreamConfig
    ) -> None:
        """Run HTTP connection lifecycle in a dedicated task.

        This method runs in its own task and owns the entire connection lifecycle.
        It enters the context managers, signals ready, waits for shutdown, then exits cleanly.
        """
        logger.debug(f"HTTP connection task started for '{config.name}'")

        # Build kwargs for streamablehttp_client
        client_kwargs: dict[str, Any] = {
            "url": config.url,
            "headers": config.headers,
            "timeout": config.timeout,
            "sse_read_timeout": config.read_timeout,
        }

        # Create custom httpx client factory if SSL verification is disabled
        if not config.verify_ssl:
            import httpx

            logger.warning(f"SSL verification disabled for upstream '{config.name}'")

            def insecure_client_factory(
                headers: dict[str, str] | None = None,
                timeout: httpx.Timeout | None = None,
                auth: httpx.Auth | None = None,
            ) -> httpx.AsyncClient:
                return httpx.AsyncClient(
                    headers=headers,
                    timeout=timeout,
                    auth=auth,
                    verify=False,
                )

            client_kwargs["httpx_client_factory"] = insecure_client_factory

        try:
            async with streamablehttp_client(**client_kwargs) as streams:
                read_stream, write_stream, _ = streams
                logger.debug(f"HTTP connection established for '{config.name}', creating session...")

                async with ClientSession(read_stream, write_stream) as session:
                    conn.session = session
                    logger.debug(f"Initializing MCP session for '{config.name}'...")
                    await session.initialize()
                    logger.debug(f"MCP session initialized for '{config.name}'")

                    # Signal that we're ready
                    conn._ready_event.set()

                    # Wait for shutdown signal
                    await conn._shutdown_event.wait()
                    logger.debug(f"HTTP connection task shutting down for '{config.name}'")

            # Context managers exit here, in the same task that entered them
            logger.debug(f"HTTP connection task completed for '{config.name}'")

        except Exception as e:
            # Store the error so it can be propagated to the caller
            conn._error = e
            conn._ready_event.set()  # Unblock anyone waiting for ready
            raise

    async def _run_sse_connection(
        self, conn: UpstreamConnection, config: SSEUpstreamConfig
    ) -> None:
        """Run SSE connection lifecycle in a dedicated task.

        This method runs in its own task and owns the entire connection lifecycle.
        It enters the context managers, signals ready, waits for shutdown, then exits cleanly.
        """
        logger.debug(f"SSE connection task started for '{config.name}'")

        # Build kwargs for sse_client
        client_kwargs: dict[str, Any] = {
            "url": config.url,
            "headers": config.headers,
        }

        # Create custom httpx client factory if SSL verification is disabled
        if not config.verify_ssl:
            import httpx

            logger.warning(f"SSL verification disabled for upstream '{config.name}'")

            def insecure_client_factory(
                headers: dict[str, str] | None = None,
                timeout: httpx.Timeout | None = None,
                auth: httpx.Auth | None = None,
            ) -> httpx.AsyncClient:
                return httpx.AsyncClient(
                    headers=headers,
                    timeout=timeout,
                    auth=auth,
                    verify=False,
                )

            client_kwargs["httpx_client_factory"] = insecure_client_factory

        try:
            async with sse_client(**client_kwargs) as streams:
                read_stream, write_stream = streams
                logger.debug(f"SSE connection established for '{config.name}', creating session...")

                async with ClientSession(read_stream, write_stream) as session:
                    conn.session = session
                    logger.debug(f"Initializing MCP session for '{config.name}'...")
                    await session.initialize()
                    logger.debug(f"MCP session initialized for '{config.name}'")

                    # Signal that we're ready
                    conn._ready_event.set()

                    # Wait for shutdown signal
                    await conn._shutdown_event.wait()
                    logger.debug(f"SSE connection task shutting down for '{config.name}'")

            # Context managers exit here, in the same task that entered them
            logger.debug(f"SSE connection task completed for '{config.name}'")

        except Exception as e:
            # Store the error so it can be propagated to the caller
            conn._error = e
            conn._ready_event.set()  # Unblock anyone waiting for ready
            raise

    async def _connect_sse(self, conn: UpstreamConnection, config: SSEUpstreamConfig) -> None:
        """Establish an SSE connection to an upstream server.

        Spawns a background task that owns the connection lifecycle.
        """
        logger.debug(f"Connecting to SSE upstream '{config.name}' at {config.url}")

        # Set up events for task coordination
        conn._ready_event = asyncio.Event()
        conn._shutdown_event = asyncio.Event()

        # Spawn the connection task
        conn._task = asyncio.create_task(
            self._run_sse_connection(conn, config),
            name=f"sse-connection-{config.name}",
        )

        # Wait for connection to be ready
        await conn._ready_event.wait()

        # Check if the task failed during setup
        if conn._error:
            raise conn._error

    async def _connect_http(
        self, conn: UpstreamConnection, config: HTTPUpstreamConfig
    ) -> None:
        """Establish an HTTP connection to an upstream server using Streamable HTTP.

        Spawns a background task that owns the connection lifecycle.
        """
        logger.debug(f"Connecting to HTTP upstream '{config.name}' at {config.url}")

        # Set up events for task coordination
        conn._ready_event = asyncio.Event()
        conn._shutdown_event = asyncio.Event()

        # Spawn the connection task
        conn._task = asyncio.create_task(
            self._run_http_connection(conn, config),
            name=f"http-connection-{config.name}",
        )

        # Wait for connection to be ready
        await conn._ready_event.wait()

        # Check if the task failed during setup
        if conn._error:
            raise conn._error

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
                if conn._shutdown_event:
                    # Task-managed connection (HTTP/SSE): signal shutdown
                    logger.debug(f"Signaling shutdown for '{conn.name}'")
                    conn._shutdown_event.set()

                if conn._task:
                    # Wait for the task to complete cleanup
                    logger.debug(f"Waiting for connection task to complete for '{conn.name}'")
                    await conn._task
                    logger.debug(f"Connection task completed for '{conn.name}'")
                else:
                    # STDIO connection: direct cleanup (no task)
                    if conn.session:
                        await conn.session.__aexit__(None, None, None)
                    if conn._cm:
                        await conn._cm.__aexit__(None, None, None)
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
