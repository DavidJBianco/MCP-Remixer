# mcp-remixer Demo

A simple demonstration of mcp-remixer features.

## What This Demo Shows

1. **Proxying an upstream server** - The MCP filesystem server
2. **Hiding a tool** - The `write_file` tool is hidden from clients
3. **Adding custom tools**:
   - `hello` - A simple greeting tool
   - `word_count` - Calls the upstream `read_file` tool and returns statistics
   - `convert_case` - Demonstrates explicit schema with enum constraints

## Prerequisites

- Node.js (for npx to run the filesystem server)
- The mcp-remixer package installed (see main README)

## Running the Demo

From the repository root:

```bash
# Run the proxy with the demo config
uv run mcp-remixer --config demo/mcp-remixer.yaml
```

## Using with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "remixer-demo": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/MCP-Remixer",
        "mcp-remixer",
        "--config", "/path/to/MCP-Remixer/demo/mcp-remixer.yaml"
      ]
    }
  }
}
```

## Expected Tools

When connected, you should see these tools:

| Tool | Source | Description |
|------|--------|-------------|
| `read_file` | filesystem upstream | Read file contents |
| `list_directory` | filesystem upstream | List directory contents |
| `hello` | custom | Say hello to someone |
| `word_count` | custom | Count lines, words, and characters |
| `convert_case` | custom | Convert text case (upper/lower/title) |

Note: `write_file` is **hidden** and will not appear in the tool list.

## Custom Tools Explained

### hello

A simple tool that takes a name and returns a greeting:

```python
@tool(description="Say hello to someone")
async def hello(name: str) -> str:
    return f"Hello, {name}! Welcome to mcp-remixer."
```

### word_count

Demonstrates calling an upstream tool from a custom tool:

```python
@tool(description="Read a file and count its lines, words, and characters")
async def word_count(path: str, upstream: UpstreamClient) -> dict:
    # Call the upstream read_file tool
    result = await upstream.call_tool("read_file", {"path": path})
    content = result.content[0].text

    # Process and return results
    return {
        "lines": len(content.split("\n")),
        "words": len(content.split()),
        "characters": len(content),
    }
```

### convert_case

Demonstrates explicit schema definition with enum constraints:

```python
@tool(
    description="Convert text to a specified case",
    parameters={
        "text": {"type": "string", "description": "The text to convert"},
        "case": {
            "type": "string",
            "enum": ["upper", "lower", "title"],
        },
    },
)
async def convert_case(text: str, case: str) -> str:
    ...
```
