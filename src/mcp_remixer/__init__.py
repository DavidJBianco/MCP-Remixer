"""
mcp-remixer: A proxy for MCP servers that lets you add custom tools,
hide existing ones, and aggregate multiple upstream servers.
"""

from mcp_remixer.exceptions import ToolError
from mcp_remixer.tool import tool
from mcp_remixer.upstream import UpstreamClient

__version__ = "0.1.0"
__all__ = ["tool", "ToolError", "UpstreamClient"]
