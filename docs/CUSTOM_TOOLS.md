# Custom Tools Guide

Custom tools let you extend mcp-remixer with your own Python functions. This guide covers everything from simple tools to advanced patterns.

## Basic Tool

```python
from mcp_remixer import tool

@tool(description="Add two numbers")
async def add(a: int, b: int) -> int:
    return a + b
```

That's it! The tool:
- Is named `add` (from the function name)
- Has description "Add two numbers"
- Takes two integer parameters (inferred from type hints)
- Returns an integer

---

## Parameter Documentation

Document parameters in the docstring:

```python
@tool(description="Search for files")
async def search_files(
    query: str,       # The search query
    max_results: int  # Maximum number of results to return
):
    """Search for files matching the query."""
    ...
```

Or use Google-style docstrings:

```python
@tool(description="Search for files")
async def search_files(query: str, max_results: int):
    """
    Search for files matching the query.

    Args:
        query: The search query
        max_results: Maximum number of results to return
    """
    ...
```

---

## Optional Parameters

Use default values for optional parameters:

```python
@tool(description="Search with options")
async def search(
    query: str,
    max_results: int = 10,
    case_sensitive: bool = False
):
    ...
```

---

## Calling Upstream Tools

Inject `UpstreamClient` to call tools from upstream servers:

```python
from mcp_remixer import tool, UpstreamClient

@tool(description="Read and transform a file")
async def transform_file(path: str, upstream: UpstreamClient):
    # Call an upstream tool
    result = await upstream.call_tool("read_file", {"path": path})
    content = result.content[0].text

    # Transform the content
    transformed = content.upper()

    return transformed
```

### UpstreamClient Methods

```python
# Call any visible tool (upstream or custom)
result = await upstream.call_tool("tool_name", {"arg": "value"})

# List all available tools
tools = await upstream.list_tools()

# Call tool on specific upstream (use full prefixed name)
result = await upstream.call_tool("filesystem.read_file", {"path": "/file"})
```

---

## Explicit Schema Definition

For complex schemas, define parameters explicitly:

```python
@tool(
    description="Create a new item",
    parameters={
        "data": {
            "type": "object",
            "description": "The item data",
            "properties": {
                "name": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "integer", "minimum": 1, "maximum": 5}
            },
            "required": ["name"]
        }
    }
)
async def create_item(data: dict, upstream: UpstreamClient):
    ...
```

### Enum Constraints

```python
@tool(
    description="Set mode",
    parameters={
        "mode": {
            "type": "string",
            "enum": ["fast", "balanced", "thorough"],
            "description": "Processing mode"
        }
    }
)
async def set_mode(mode: str):
    ...
```

---

## Return Values

Tools can return various types:

```python
# String (becomes TextContent)
@tool(description="Greet")
async def greet(name: str) -> str:
    return f"Hello, {name}!"

# Dict (becomes JSON in TextContent)
@tool(description="Get stats")
async def get_stats() -> dict:
    return {"count": 42, "status": "ok"}

# List of content (for multiple outputs)
from mcp.types import TextContent

@tool(description="Analyze")
async def analyze(path: str) -> list:
    return [
        TextContent(type="text", text="Analysis complete"),
        TextContent(type="text", text="Found 5 issues")
    ]
```

---

## Error Handling

Raise exceptions for errors - they're converted to MCP errors:

```python
@tool(description="Divide numbers")
async def divide(a: int, b: int):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

For more control, raise `ToolError`:

```python
from mcp_remixer import tool, ToolError

@tool(description="Process data")
async def process(data: str):
    if not data:
        raise ToolError("INVALID_INPUT", "Data cannot be empty")
    ...
```

---

## Sync vs Async

Both sync and async functions work:

```python
# Async (preferred for I/O operations)
@tool(description="Fetch data")
async def fetch_data(url: str):
    ...

# Sync (fine for CPU-bound operations)
@tool(description="Calculate hash")
def calculate_hash(data: str) -> str:
    import hashlib
    return hashlib.sha256(data.encode()).hexdigest()
```

---

## Complete Examples

### File Summarizer

```python
from mcp_remixer import tool, UpstreamClient

@tool(description="Read a file and return a summary with metadata")
async def summarize_file(
    path: str,            # Path to the file
    max_lines: int = 50,  # Maximum lines to include in summary
    upstream: UpstreamClient = None
):
    """Read a file and return first N lines with file stats."""

    # Read the file via upstream
    result = await upstream.call_tool("read_file", {"path": path})
    content = result.content[0].text

    lines = content.split("\n")
    total_lines = len(lines)
    preview = "\n".join(lines[:max_lines])

    return {
        "path": path,
        "total_lines": total_lines,
        "preview_lines": min(max_lines, total_lines),
        "preview": preview
    }
```

### Validated Write

```python
import json
from mcp_remixer import tool, ToolError, UpstreamClient

@tool(
    description="Write JSON to a file with validation",
    parameters={
        "path": {"type": "string", "description": "Output file path"},
        "data": {"type": "object", "description": "JSON data to write"},
        "pretty": {"type": "boolean", "description": "Pretty print", "default": True}
    }
)
async def write_json(
    path: str,
    data: dict,
    pretty: bool = True,
    upstream: UpstreamClient = None
):
    """Write validated JSON to a file."""

    if not path.endswith(".json"):
        raise ToolError("INVALID_PATH", "Path must end with .json")

    try:
        if pretty:
            content = json.dumps(data, indent=2)
        else:
            content = json.dumps(data)
    except TypeError as e:
        raise ToolError("INVALID_JSON", f"Data is not JSON serializable: {e}")

    await upstream.call_tool("write_file", {
        "path": path,
        "content": content
    })

    return f"Wrote {len(content)} bytes to {path}"
```

### Multi-Tool Orchestration

```python
from mcp_remixer import tool, UpstreamClient

@tool(description="Search git history and read the matching file")
async def search_and_read(
    query: str,       # Search query for git log
    upstream: UpstreamClient = None
):
    """Search git commits and return file contents from matching commit."""

    # Search git history
    search_result = await upstream.call_tool("git.search_commits", {
        "query": query
    })

    commits = search_result.content[0].text
    if not commits:
        return "No matching commits found"

    # Parse first commit
    first_commit = commits.split("\n")[0]
    commit_hash = first_commit.split()[0]

    # Get files changed in that commit
    files_result = await upstream.call_tool("git.get_commit_files", {
        "commit": commit_hash
    })

    return {
        "commit": commit_hash,
        "files": files_result.content[0].text
    }
```

---

## Testing Custom Tools

```python
# tests/test_my_tools.py
import pytest
from unittest.mock import AsyncMock
from mcp.types import TextContent, CallToolResult

from my_tools import summarize_file

@pytest.fixture
def mock_upstream():
    mock = AsyncMock()
    mock.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text="line1\nline2\nline3")]
    )
    return mock

@pytest.mark.asyncio
async def test_summarize_file(mock_upstream):
    result = await summarize_file(
        path="/test.txt",
        max_lines=2,
        upstream=mock_upstream
    )

    assert result["total_lines"] == 3
    assert result["preview_lines"] == 2
    mock_upstream.call_tool.assert_called_once_with(
        "read_file",
        {"path": "/test.txt"}
    )
```

---

## Best Practices

1. **Use async for I/O** - Prefer `async def` for tools that call upstream or do network I/O
2. **Validate early** - Check inputs at the start of your function
3. **Return structured data** - Return dicts for complex results; they're JSON serialized automatically
4. **Document parameters** - Use type hints and docstrings for automatic schema generation
5. **Handle errors gracefully** - Use `ToolError` for user-facing errors with clear messages
6. **Test with mocks** - Inject mock `UpstreamClient` for unit testing
