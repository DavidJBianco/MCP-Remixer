# Configuration Reference

mcp-remixer uses a YAML configuration file. By default, it looks for `mcp-remixer.yaml` in the current directory.

## Full Example

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"]
    env:
      DEBUG: "true"
    required: true
    tool_prefix: "fs_"

  git:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-git"]
    required: false

  remote_api:
    transport: sse
    url: "http://localhost:8080/mcp"
    headers:
      Authorization: "Bearer ${API_TOKEN}"

  cloud_service:
    transport: http
    url: "https://api.example.com/mcp"
    headers:
      Authorization: "Bearer ${CLOUD_API_TOKEN}"
    timeout: 60
    read_timeout: 600
    required: true
    tool_prefix: "cloud_"

hidden:
  tools:
    - "filesystem.write_file"
    - "dangerous_operation"
  prompts: []
  resources: []

custom_tools:
  - "./tools/summarize.py"
  - "./tools/validators.py"
```

---

## Top-Level Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `upstreams` | object | Yes | Map of upstream server configurations |
| `hidden` | object | No | Items to hide from clients |
| `custom_tools` | list | No | Paths to Python modules with custom tools |

---

## Upstream Configuration

Each key under `upstreams` is the upstream name (used for prefixing and routing).

### stdio Transport

For MCP servers launched as subprocesses.

```yaml
upstreams:
  myserver:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    env:
      DEBUG: "true"
    required: false
    tool_prefix: "fs_"
```

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `transport` | string | Yes | - | Must be `"stdio"` |
| `command` | string | Yes | - | Command to execute |
| `args` | list | No | `[]` | Command arguments |
| `env` | object | No | `{}` | Environment variables (supports `${VAR}` expansion) |
| `required` | boolean | No | `false` | If true, proxy fails to start if connection fails |
| `tool_prefix` | string | No | `""` | Prefix added to all tools from this upstream |

### SSE Transport

For remote MCP servers using Server-Sent Events.

```yaml
upstreams:
  remote:
    transport: sse
    url: "http://localhost:8080/mcp"
    headers:
      Authorization: "Bearer ${API_TOKEN}"
    required: false
    tool_prefix: ""

  # Example with self-signed certificate
  internal_sse:
    transport: sse
    url: "https://internal.example.com/mcp"
    verify_ssl: false
```

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `transport` | string | Yes | - | Must be `"sse"` |
| `url` | string | Yes | - | SSE endpoint URL |
| `headers` | object | No | `{}` | HTTP headers (supports `${VAR}` expansion) |
| `verify_ssl` | boolean | No | `true` | Verify SSL certificates. Set to `false` for self-signed certs |
| `required` | boolean | No | `false` | If true, proxy fails to start if connection fails |
| `tool_prefix` | string | No | `""` | Prefix added to all tools from this upstream |

### HTTP Transport

For remote MCP servers using the Streamable HTTP protocol. This is the modern HTTP-based transport for MCP that supports bidirectional streaming over HTTP.

```yaml
upstreams:
  cloud_api:
    transport: http
    url: "https://api.example.com/mcp"
    headers:
      Authorization: "Bearer ${API_TOKEN}"
    timeout: 30
    read_timeout: 300
    required: true
    tool_prefix: "cloud_"

  # Example with self-signed certificate
  internal_server:
    transport: http
    url: "https://internal.example.com:8089/mcp"
    verify_ssl: false  # Disable SSL verification for self-signed certs
```

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `transport` | string | Yes | - | Must be `"http"` |
| `url` | string | Yes | - | HTTP/HTTPS endpoint URL |
| `headers` | object | No | `{}` | HTTP headers (supports `${VAR}` expansion) |
| `timeout` | number | No | `30` | HTTP operation timeout in seconds |
| `read_timeout` | number | No | `300` | Read timeout in seconds (how long to wait for server responses) |
| `verify_ssl` | boolean | No | `true` | Verify SSL certificates. Set to `false` for self-signed certs |
| `required` | boolean | No | `false` | If true, proxy fails to start if connection fails |
| `tool_prefix` | string | No | `""` | Prefix added to all tools from this upstream |

---

## Hidden Items

Control which items from upstreams are hidden from clients.

```yaml
hidden:
  tools:
    - "write_file"              # Hide from any upstream
    - "filesystem.write_file"   # Hide only from 'filesystem' upstream
  prompts: []                   # Reserved for future use
  resources: []                 # Reserved for future use
```

Hidden tools:
- Do not appear in `tools/list` responses
- Return an error if a client tries to call them

---

## Custom Tools

Paths to Python modules containing `@tool` decorated functions.

```yaml
custom_tools:
  - "./tools/my_tools.py"
  - "./tools/validators.py"
  - "/absolute/path/to/tools.py"
```

- Relative paths are resolved from the config file's directory
- All `@tool` decorated functions in each module are loaded
- See [Custom Tools Guide](CUSTOM_TOOLS.md) for writing tools

---

## Tool Name Resolution

When aggregating tools from multiple upstreams, mcp-remixer automatically resolves naming conflicts to ensure each tool has a unique name.

### Resolution Rules

Tool names are resolved in this order:

| Scenario | Result |
|----------|--------|
| Tool name is unique across all upstreams | Original name (e.g., `read_file`) |
| `tool_prefix` is configured | Prefix applied (e.g., `fs_read_file`) |
| Name collision between upstreams | Auto-prefix with upstream name (e.g., `server_a.search`) |
| Upstream tool collides with custom tool | Custom tool keeps name, upstream tools get prefixed |

### Example: No collision (unique names)

```yaml
upstreams:
  filesystem:  # provides: read_file, write_file, list_directory
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]

  git:  # provides: git_status, git_commit, git_log
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-git"]
```

**Exposed tools:** `read_file`, `write_file`, `list_directory`, `git_status`, `git_commit`, `git_log`

All names are unique, so no prefixing is needed.

### Example: Auto-prefix on collision

```yaml
upstreams:
  slack:
    transport: stdio
    command: "npx"
    args: ["-y", "@anthropic/server-slack"]
    # provides: search, list_channels, post_message

  github:
    transport: stdio
    command: "npx"
    args: ["-y", "@anthropic/server-github"]
    # also provides: search, list_repos, create_issue
```

**Exposed tools:**
- `slack.search`, `list_channels`, `post_message`
- `github.search`, `list_repos`, `create_issue`

Only the conflicting `search` tool gets prefixed with the upstream name. Non-conflicting tools keep their original names.

### Example: Explicit prefix

```yaml
upstreams:
  server_a:
    transport: stdio
    command: "..."
    tool_prefix: "a_"
    # has "search" tool → exposed as "a_search"

  server_b:
    transport: stdio
    command: "..."
    tool_prefix: "b_"
    # has "search" tool → exposed as "b_search"
```

**Exposed tools:** `a_search`, `b_search`

With explicit `tool_prefix`, the prefix is always applied regardless of collisions.

### Example: Custom tool takes priority

```yaml
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    # provides: read_file, write_file

custom_tools:
  - "./tools/my_tools.py"  # defines: read_file (custom implementation)
```

**Exposed tools:**
- `read_file` (custom tool)
- `filesystem.read_file` (upstream tool, auto-prefixed)
- `write_file` (upstream tool, no conflict)

Custom tools always keep their original name. Conflicting upstream tools are auto-prefixed.

### Calling prefixed tools from custom tools

When calling upstream tools from custom tools, use the **original** tool name (not the prefixed name):

```python
from mcp_remixer import tool, UpstreamClient

@tool(description="Read and process a file")
async def process_file(path: str, upstream: UpstreamClient):
    # Use original name "read_file", not "fs_read_file" or "filesystem.read_file"
    result = await upstream.call_tool("read_file", {"path": path})
    return result.content[0].text
```

The `UpstreamClient` routes the call to the correct upstream automatically.

---

## Environment Variable Expansion

Use `${VAR_NAME}` in string values to expand environment variables:

```yaml
upstreams:
  remote:
    transport: sse
    url: "${MCP_SERVER_URL}"
    headers:
      Authorization: "Bearer ${API_TOKEN}"
```

Missing variables cause an error at startup.

### .env File Support

mcp-remixer automatically loads `.env` files:

1. `.env` in the current working directory
2. `.env` in the config file's directory (higher priority)

Example `.env` file:

```bash
API_TOKEN=secret-token-12345
MCP_SERVER_URL=http://localhost:8080/mcp
```

---

## Command Line Options

```bash
uv run mcp-remixer [OPTIONS]

Options:
  --config, -c PATH    Path to config file (default: ./mcp-remixer.yaml)
  --verbose, -v        Enable verbose logging
  --version            Show version and exit
  --help               Show help and exit
```

### Examples

```bash
# Use default config location
uv run mcp-remixer

# Use specific config file
uv run mcp-remixer --config /path/to/config.yaml

# Enable debug logging
uv run mcp-remixer --verbose
```
