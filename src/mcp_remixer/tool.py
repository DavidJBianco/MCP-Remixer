"""Tool decorator and schema inference for custom tools."""

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable, get_args, get_origin

from mcp_remixer.exceptions import ToolError

# Type mapping from Python types to JSON Schema types
TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass
class ToolDefinition:
    """Represents a custom tool definition."""

    name: str
    description: str
    function: Callable
    parameters: dict[str, Any]
    is_async: bool


# Global registry of custom tools defined with @tool decorator
_custom_tools: dict[str, ToolDefinition] = {}


def get_custom_tools() -> dict[str, ToolDefinition]:
    """Get all registered custom tools."""
    return _custom_tools.copy()


def clear_custom_tools() -> None:
    """Clear all registered custom tools. Useful for testing."""
    _custom_tools.clear()


def _parse_docstring_params(docstring: str | None) -> dict[str, str]:
    """Extract parameter descriptions from a docstring.

    Supports both inline comments style and Google-style Args section.
    """
    if not docstring:
        return {}

    descriptions = {}

    # Try Google-style Args section
    args_match = re.search(r"Args:\s*\n((?:\s+\w+.*\n?)+)", docstring)
    if args_match:
        args_section = args_match.group(1)
        # Match lines like "    param_name: description" or "    param_name (type): description"
        for match in re.finditer(r"^\s+(\w+)(?:\s*\([^)]*\))?\s*:\s*(.+?)(?=\n\s+\w+|\Z)", args_section, re.MULTILINE | re.DOTALL):
            param_name = match.group(1)
            description = match.group(2).strip()
            # Clean up multiline descriptions
            description = re.sub(r"\s+", " ", description)
            descriptions[param_name] = description

    return descriptions


def _parse_inline_comments(source: str, param_names: list[str]) -> dict[str, str]:
    """Extract parameter descriptions from inline comments after parameters."""
    descriptions = {}

    for param in param_names:
        # Look for patterns like "param_name: type,  # description" or "param_name: type  # description"
        pattern = rf"{param}\s*:\s*[^,#\n]+[,\s]*#\s*(.+?)(?:\n|$)"
        match = re.search(pattern, source)
        if match:
            descriptions[param] = match.group(1).strip()

    return descriptions


def _get_json_schema_type(python_type: type) -> dict[str, Any]:
    """Convert a Python type to a JSON Schema type definition."""
    # Handle None type
    if python_type is type(None):
        return {"type": "null"}

    # Handle basic types
    if python_type in TYPE_MAP:
        return {"type": TYPE_MAP[python_type]}

    # Handle generic types (list[str], dict[str, int], etc.)
    origin = get_origin(python_type)
    args = get_args(python_type)

    if origin is list:
        schema: dict[str, Any] = {"type": "array"}
        if args:
            schema["items"] = _get_json_schema_type(args[0])
        return schema

    if origin is dict:
        schema = {"type": "object"}
        if len(args) >= 2:
            schema["additionalProperties"] = _get_json_schema_type(args[1])
        return schema

    # Handle Union types (X | Y or Union[X, Y])
    if origin is type(int | str):  # UnionType
        # Check for Optional (X | None)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1 and len(args) == 2:
            # This is Optional[X]
            return _get_json_schema_type(non_none_args[0])
        # Multiple types - use anyOf
        return {"anyOf": [_get_json_schema_type(a) for a in args]}

    # Default to string for unknown types
    return {"type": "string"}


def _infer_schema(func: Callable) -> tuple[dict[str, Any], list[str]]:
    """Infer JSON Schema from function signature and docstring.

    Returns:
        Tuple of (schema dict, list of required parameter names)
    """
    sig = inspect.signature(func)
    type_hints = {}
    try:
        type_hints = {k: v for k, v in inspect.get_annotations(func).items() if k != "return"}
    except Exception:
        pass

    # Get docstring descriptions
    docstring_descriptions = _parse_docstring_params(func.__doc__)

    # Try to get inline comment descriptions from source
    inline_descriptions: dict[str, str] = {}
    try:
        source = inspect.getsource(func)
        param_names = [p for p in sig.parameters if p not in ("upstream", "self", "cls")]
        inline_descriptions = _parse_inline_comments(source, param_names)
    except (OSError, TypeError):
        pass

    # Build schema
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        # Skip special parameters
        if param_name in ("upstream", "self", "cls"):
            continue

        # Skip *args and **kwargs
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        # Get type
        param_type = type_hints.get(param_name, str)

        # Check if it's UpstreamClient type (by name check to avoid import issues)
        type_name = getattr(param_type, "__name__", str(param_type))
        if "UpstreamClient" in type_name:
            continue

        # Build property schema
        prop_schema = _get_json_schema_type(param_type)

        # Add description (inline comments take precedence over docstring)
        description = inline_descriptions.get(param_name) or docstring_descriptions.get(param_name)
        if description:
            prop_schema["description"] = description

        # Check if required (no default value)
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            # Add default value if it's a simple type
            if param.default is not None and isinstance(param.default, (str, int, float, bool)):
                prop_schema["default"] = param.default

        properties[param_name] = prop_schema

    schema = {
        "type": "object",
        "properties": properties,
    }

    if required:
        schema["required"] = required

    return schema, required


def tool(
    description: str,
    name: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> Callable[[Callable], Callable]:
    """Decorator to register a function as an MCP tool.

    Args:
        description: Human-readable description of the tool.
        name: Optional tool name. Defaults to the function name.
        parameters: Optional explicit JSON Schema for parameters.
                   If not provided, schema is inferred from type hints.

    Example:
        @tool(description="Add two numbers")
        async def add(a: int, b: int) -> int:
            return a + b

        @tool(
            description="Search with mode",
            parameters={
                "query": {"type": "string", "description": "Search query"},
                "mode": {"type": "string", "enum": ["fast", "deep"]}
            }
        )
        async def search(query: str, mode: str, upstream: UpstreamClient):
            ...
    """

    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__

        # Build parameter schema
        if parameters is not None:
            # Use explicit schema
            schema = {
                "type": "object",
                "properties": parameters,
                "required": [k for k, v in parameters.items() if "default" not in v],
            }
        else:
            # Infer schema from function signature
            schema, _ = _infer_schema(func)

        # Create tool definition
        tool_def = ToolDefinition(
            name=tool_name,
            description=description,
            function=func,
            parameters=schema,
            is_async=inspect.iscoroutinefunction(func),
        )

        # Register the tool
        _custom_tools[tool_name] = tool_def

        return func

    return decorator


# Re-export ToolError for convenience
__all__ = ["tool", "ToolError", "ToolDefinition", "get_custom_tools", "clear_custom_tools"]
