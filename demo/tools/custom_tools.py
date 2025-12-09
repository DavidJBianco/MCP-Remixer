"""Demo custom tools for mcp-remixer."""

from mcp_remixer import tool, UpstreamClient


@tool(name="remixer_hello", description="Say hello to someone")
async def hello(name: str) -> str:
    """A simple greeting tool.

    Args:
        name: The name of the person to greet
    """
    return f"Hello, {name}! Welcome to mcp-remixer."


@tool(name="remixer_word_count", description="Read a file and count its lines, words, and characters")
async def word_count(path: str, upstream: UpstreamClient) -> dict:
    """Read a file using the upstream filesystem server and return statistics.

    This demonstrates how a custom tool can call an upstream tool.

    Args:
        path: Path to the file to analyze
    """
    # Call the upstream read_file tool
    result = await upstream.call_tool("read_file", {"path": path})
    content = result.content[0].text

    lines = content.split("\n")
    words = content.split()
    chars = len(content)

    return {
        "path": path,
        "lines": len(lines),
        "words": len(words),
        "characters": chars,
    }


@tool(
    name="remixer_convert_case",
    description="Convert text to a specified case",
    parameters={
        "text": {"type": "string", "description": "The text to convert"},
        "case": {
            "type": "string",
            "description": "Target case",
            "enum": ["upper", "lower", "title"],
        },
    },
)
async def convert_case(text: str, case: str) -> str:
    """Convert text to uppercase, lowercase, or title case.

    This demonstrates explicit schema definition with enum constraints.

    Args:
        text: The text to convert
        case: One of 'upper', 'lower', or 'title'
    """
    if case == "upper":
        return text.upper()
    elif case == "lower":
        return text.lower()
    elif case == "title":
        return text.title()
    else:
        return text
