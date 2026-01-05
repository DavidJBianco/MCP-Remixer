# Quick Start

Get mcp-remixer running in 5 minutes.

## 1. Install

```bash
# Clone the repository
git clone https://github.com/DavidJBianco/MCP-Remixer.git
cd MCP-Remixer

# Install dependencies
uv sync
```

## 2. Create config file

Create `mcp-remixer.yaml` in your project directory:

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

## 3. Run it

```bash
uv run mcp-remixer --config mcp-remixer.yaml
```

You now have a proxy running in front of the filesystem MCP server.

## 4. Add a custom tool

Create `tools/hello.py`:

```python
from mcp_remixer import tool

@tool(description="Say hello")
async def say_hello(name: str):
    return f"Hello, {name}!"
```

Update `mcp-remixer.yaml`:

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]

custom_tools:
  - "./tools/hello.py"
```

Restart the proxy. Your `say_hello` tool is now available alongside the filesystem tools.

## 5. Hide an upstream tool

Add a `hidden` section to your config:

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]

hidden:
  tools:
    - "write_file"  # Clients can't see or use this

custom_tools:
  - "./tools/hello.py"
```

## 6. Add multiple upstreams

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    tool_prefix: "fs_"  # Tools become fs_read_file, fs_write_file, etc.

  git:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-git"]
    tool_prefix: "git_"

hidden:
  tools:
    - "fs_write_file"

custom_tools:
  - "./tools/hello.py"
```

## 7. Understand tool naming

When you aggregate multiple upstreams, tool names are handled automatically:

**No conflicts (unique names):** Tools keep their original names.

```yaml
upstreams:
  filesystem:  # has: read_file, write_file
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
  git:  # has: git_status, git_commit
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-git"]
```

Result: `read_file`, `write_file`, `git_status`, `git_commit` (no prefixes needed)

**With conflicts (same tool name):** Tools are auto-prefixed with the upstream name.

```yaml
upstreams:
  slack:  # has: search
    transport: stdio
    command: "npx"
    args: ["-y", "@anthropic/server-slack"]
  github:  # also has: search
    transport: stdio
    command: "npx"
    args: ["-y", "@anthropic/server-github"]
```

Result: `slack.search` and `github.search` (auto-prefixed to avoid collision)

**Explicit prefixes:** Use `tool_prefix` to always add a prefix regardless of collisions.

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    tool_prefix: "fs_"  # read_file becomes fs_read_file
```

See the [Configuration Reference](docs/CONFIGURATION.md#tool-name-resolution) for full details.

## 8. Use with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-remix": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/MCP-Remixer", "mcp-remixer", "--config", "/absolute/path/to/mcp-remixer.yaml"]
    }
  }
}
```

Replace `/path/to/MCP-Remixer` with the actual path where you cloned the repository.

Restart Claude Desktop.

## 9. Chain tools together

Create a custom tool that calls an upstream tool:

```python
# tools/smart_tools.py
from mcp_remixer import tool, UpstreamClient

@tool(description="Read a file and count its lines")
async def count_lines(path: str, upstream: UpstreamClient):
    # Call the upstream filesystem tool
    result = await upstream.call_tool("fs_read_file", {"path": path})
    content = result.content[0].text

    line_count = len(content.split("\n"))
    return f"File {path} has {line_count} lines"
```

## 10. Enable audit logging

Track all MCP transactions for debugging or compliance:

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]

audit:
  enabled: true
  log_file: ./audit.jsonl
  truncate: true  # Recommended: truncate large responses
  max_content_length: 1024
```

Each client session gets a unique `session_id` (UUID), making it easy to trace requests across multiple concurrent clients.

See [Audit Logging](docs/CONFIGURATION.md#audit-logging) for full details.

## Next Steps

- [Configuration Reference](docs/CONFIGURATION.md) - All config options
- [Custom Tools Guide](docs/CUSTOM_TOOLS.md) - Advanced tool patterns
