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
    transport: streamable_http
    url: "https://api.example.com/mcp"
    headers:
      Authorization: "Bearer ${CLOUD_API_TOKEN}"
    timeout: 60
    sse_read_timeout: 600
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
```

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `transport` | string | Yes | - | Must be `"sse"` |
| `url` | string | Yes | - | SSE endpoint URL |
| `headers` | object | No | `{}` | HTTP headers (supports `${VAR}` expansion) |
| `required` | boolean | No | `false` | If true, proxy fails to start if connection fails |
| `tool_prefix` | string | No | `""` | Prefix added to all tools from this upstream |

### Streamable HTTP Transport

For remote MCP servers using the Streamable HTTP protocol. This is the modern HTTP-based transport for MCP that supports bidirectional streaming over HTTP.

```yaml
upstreams:
  cloud_api:
    transport: streamable_http
    url: "https://api.example.com/mcp"
    headers:
      Authorization: "Bearer ${API_TOKEN}"
    timeout: 30
    sse_read_timeout: 300
    required: true
    tool_prefix: "cloud_"
```

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `transport` | string | Yes | - | Must be `"streamable_http"` |
| `url` | string | Yes | - | HTTP/HTTPS endpoint URL |
| `headers` | object | No | `{}` | HTTP headers (supports `${VAR}` expansion) |
| `timeout` | number | No | `30` | HTTP operation timeout in seconds |
| `sse_read_timeout` | number | No | `300` | SSE read timeout in seconds (how long to wait for events) |
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

When tools from multiple upstreams have the same name:

1. **Explicit prefix wins** - If `tool_prefix` is set, it's always applied
2. **Auto-prefix on collision** - Conflicting names get `upstream_name.` prefix
3. **Flat if unique** - No prefix if the name is unique across all upstreams

### Example with collision:

```yaml
upstreams:
  server_a:
    transport: stdio
    command: "..."
    # has "search" tool
  server_b:
    transport: stdio
    command: "..."
    # also has "search" tool
```

Result: Tools exposed as `server_a.search` and `server_b.search`

### Example with explicit prefix:

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
