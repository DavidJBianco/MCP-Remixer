# mcp-remixer

A proxy for MCP servers that lets you add custom tools, hide existing ones, and aggregate multiple upstream servers into a single interface.

## Features

- **Aggregate multiple MCP servers** - Combine multiple MCP servers into one
- **Automatic tool name resolution** - Handles conflicting tool names across upstream stream (e.g., `server_a.search` vs `server_b.search`)
- **Add custom tools** - Write Python functions that become MCP tools
- **Hide tools** - Filter out tools you don't want exposed
- **Chain tools** - Custom tools can call upstream tools
- **Graceful degradation** - Optional upstreams won't block startup
- **Environment variable support** - Use `.env` files and `${VAR}` expansion

## Installation

```bash
# Clone the repository
git clone https://github.com/DavidJBianco/MCP-Remixer.git
cd MCP-Remixer

# Install dependencies
uv sync
```

## Quick Example

```yaml
# mcp-remixer.yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"]

hidden:
  tools:
    - "write_file"  # Hide this tool from clients

custom_tools:
  - "./tools/my_tools.py"
```

```python
# tools/my_tools.py
from mcp_remixer import tool, UpstreamClient

@tool(description="Read and summarize a file")
async def summarize_file(path: str, upstream: UpstreamClient):
    result = await upstream.call_tool("read_file", {"path": path})
    content = result.content[0].text
    return f"Summary: {content[:100]}..."
```

```bash
uv run mcp-remixer --config mcp-remixer.yaml
```

## Documentation

- [Quick Start Guide](QUICKSTART.md) - Get running in 5 minutes
- [Configuration Reference](docs/CONFIGURATION.md) - All config options explained
- [Custom Tools Guide](docs/CUSTOM_TOOLS.md) - Writing your own tools

## Using with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-remix": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/MCP-Remixer", "mcp-remixer", "--config", "/path/to/mcp-remixer.yaml"]
    }
  }
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Client (Claude)                     │
└─────────────────────────────┬───────────────────────────────┘
                              │ stdio
┌─────────────────────────────▼───────────────────────────────┐
│                       mcp-remixer                            │
│  • Merge tools from upstreams                                │
│  • Apply prefixes / resolve collisions                       │
│  • Filter hidden tools                                       │
│  • Register custom tools                                     │
│  • Route tool calls to correct destination                   │
└─────────────────────────────────────────────────────────────┘
        │ stdio               │ sse/http            │ http
┌───────▼───────┐  ┌─────────▼────────┐  ┌────────▼────────┐
│  filesystem   │  │    remote_api    │  │  cloud_service  │
│    server     │  │     server       │  │     server      │
└───────────────┘  └──────────────────┘  └─────────────────┘
```

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=mcp_remixer --cov-report=html
```

## License

MIT
