"""Custom exceptions for mcp-remixer."""


class MCPRemixerError(Exception):
    """Base exception for mcp-remixer."""

    pass


class ConfigError(MCPRemixerError):
    """Error in configuration file."""

    pass


class UpstreamError(MCPRemixerError):
    """Error communicating with upstream server."""

    pass


class ToolError(MCPRemixerError):
    """Error raised by custom tools."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ToolNotFoundError(MCPRemixerError):
    """Requested tool does not exist."""

    pass


class ToolHiddenError(MCPRemixerError):
    """Requested tool is hidden."""

    pass
