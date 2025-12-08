"""Simple custom tools for testing."""

from mcp_remixer import tool


@tool(description="Say hello to someone")
async def hello(name: str):
    """Greet someone by name.

    Args:
        name: The name of the person to greet
    """
    return f"Hello, {name}!"


@tool(description="Add two numbers")
def add(a: int, b: int) -> int:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number
    """
    return a + b


@tool(description="Convert text to uppercase")
async def uppercase(text: str) -> str:
    """Convert text to uppercase.

    Args:
        text: The text to convert
    """
    return text.upper()
