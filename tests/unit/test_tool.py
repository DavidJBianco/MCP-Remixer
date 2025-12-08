"""Tests for tool decorator and schema inference."""

import pytest

from mcp_remixer.tool import (
    tool,
    get_custom_tools,
    clear_custom_tools,
    _infer_schema,
    _get_json_schema_type,
    _parse_docstring_params,
)


class TestGetJsonSchemaType:
    """Tests for Python type to JSON Schema conversion."""

    def test_string_type(self):
        """Converts str to string schema."""
        result = _get_json_schema_type(str)
        assert result == {"type": "string"}

    def test_int_type(self):
        """Converts int to integer schema."""
        result = _get_json_schema_type(int)
        assert result == {"type": "integer"}

    def test_float_type(self):
        """Converts float to number schema."""
        result = _get_json_schema_type(float)
        assert result == {"type": "number"}

    def test_bool_type(self):
        """Converts bool to boolean schema."""
        result = _get_json_schema_type(bool)
        assert result == {"type": "boolean"}

    def test_list_type(self):
        """Converts list to array schema."""
        result = _get_json_schema_type(list)
        assert result == {"type": "array"}

    def test_list_with_item_type(self):
        """Converts list[str] to array with items schema."""
        result = _get_json_schema_type(list[str])
        assert result == {"type": "array", "items": {"type": "string"}}

    def test_dict_type(self):
        """Converts dict to object schema."""
        result = _get_json_schema_type(dict)
        assert result == {"type": "object"}

    def test_dict_with_value_type(self):
        """Converts dict[str, int] to object with additionalProperties."""
        result = _get_json_schema_type(dict[str, int])
        assert result == {"type": "object", "additionalProperties": {"type": "integer"}}

    def test_optional_type(self):
        """Converts str | None to string schema (optional handling)."""
        result = _get_json_schema_type(str | None)
        assert result == {"type": "string"}

    def test_union_type(self):
        """Converts str | int to anyOf schema."""
        result = _get_json_schema_type(str | int)
        assert result == {"anyOf": [{"type": "string"}, {"type": "integer"}]}


class TestParseDocstringParams:
    """Tests for docstring parameter parsing."""

    def test_google_style_docstring(self):
        """Parses Google-style Args section."""
        docstring = """
        Do something.

        Args:
            name: The name to use
            count: Number of items
        """
        result = _parse_docstring_params(docstring)
        assert result == {
            "name": "The name to use",
            "count": "Number of items",
        }

    def test_google_style_with_types(self):
        """Parses Google-style Args with type annotations."""
        docstring = """
        Do something.

        Args:
            name (str): The name to use
            count (int): Number of items
        """
        result = _parse_docstring_params(docstring)
        assert result == {
            "name": "The name to use",
            "count": "Number of items",
        }

    def test_empty_docstring(self):
        """Returns empty dict for None docstring."""
        result = _parse_docstring_params(None)
        assert result == {}

    def test_no_args_section(self):
        """Returns empty dict when no Args section."""
        docstring = "Just a simple docstring."
        result = _parse_docstring_params(docstring)
        assert result == {}


class TestInferSchema:
    """Tests for schema inference from function signatures."""

    def test_simple_function(self):
        """Infers schema from simple function."""
        def func(name: str, count: int):
            pass

        schema, required = _infer_schema(func)

        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert "count" in schema["properties"]
        assert schema["properties"]["count"]["type"] == "integer"
        assert set(required) == {"name", "count"}

    def test_optional_parameters(self):
        """Handles optional parameters with defaults."""
        def func(name: str, count: int = 10):
            pass

        schema, required = _infer_schema(func)

        assert required == ["name"]
        assert schema["properties"]["count"].get("default") == 10

    def test_skips_upstream_parameter(self):
        """Skips 'upstream' parameter from schema."""
        def func(name: str, upstream):
            pass

        schema, required = _infer_schema(func)

        assert "upstream" not in schema["properties"]
        assert "name" in schema["properties"]

    def test_skips_self_and_cls(self):
        """Skips 'self' and 'cls' parameters."""
        def func(self, name: str, cls):
            pass

        schema, required = _infer_schema(func)

        assert "self" not in schema["properties"]
        assert "cls" not in schema["properties"]
        assert "name" in schema["properties"]


class TestToolDecorator:
    """Tests for the @tool decorator."""

    def test_basic_tool_registration(self):
        """Registers a basic tool."""
        @tool(description="Say hello")
        async def hello(name: str):
            return f"Hello, {name}!"

        tools = get_custom_tools()
        assert "hello" in tools
        assert tools["hello"].description == "Say hello"
        assert tools["hello"].is_async is True

    def test_sync_tool_registration(self):
        """Registers a sync tool."""
        @tool(description="Add numbers")
        def add(a: int, b: int) -> int:
            return a + b

        tools = get_custom_tools()
        assert "add" in tools
        assert tools["add"].is_async is False

    def test_custom_name(self):
        """Allows custom tool name."""
        @tool(description="Say hello", name="greet")
        async def hello(name: str):
            return f"Hello, {name}!"

        tools = get_custom_tools()
        assert "greet" in tools
        assert "hello" not in tools

    def test_explicit_schema(self):
        """Uses explicit parameter schema when provided."""
        @tool(
            description="Search",
            parameters={
                "query": {"type": "string", "description": "Search query"},
                "mode": {"type": "string", "enum": ["fast", "deep"]},
            }
        )
        async def search(query: str, mode: str):
            pass

        tools = get_custom_tools()
        schema = tools["search"].parameters
        assert schema["properties"]["mode"]["enum"] == ["fast", "deep"]

    def test_schema_inference(self):
        """Infers schema from type hints."""
        @tool(description="Process data")
        async def process(text: str, count: int, active: bool = True):
            pass

        tools = get_custom_tools()
        schema = tools["process"].parameters

        assert schema["properties"]["text"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["active"]["type"] == "boolean"
        assert schema["properties"]["active"]["default"] is True
        assert "text" in schema["required"]
        assert "count" in schema["required"]
        assert "active" not in schema["required"]

    def test_decorator_returns_original_function(self):
        """Decorator returns the original function unchanged."""
        @tool(description="Test")
        async def my_func(x: int) -> int:
            return x * 2

        # Function should still work
        import asyncio
        result = asyncio.run(my_func(5))
        assert result == 10

    def test_multiple_tools_registration(self):
        """Multiple tools can be registered."""
        @tool(description="Tool 1")
        async def tool1():
            pass

        @tool(description="Tool 2")
        async def tool2():
            pass

        tools = get_custom_tools()
        assert "tool1" in tools
        assert "tool2" in tools

    def test_clear_tools(self):
        """clear_custom_tools removes all registered tools."""
        @tool(description="Test")
        async def my_tool():
            pass

        assert len(get_custom_tools()) == 1

        clear_custom_tools()

        assert len(get_custom_tools()) == 0

    def test_upstream_parameter_not_in_schema(self):
        """UpstreamClient parameter is excluded from schema."""
        from mcp_remixer.upstream import UpstreamClient

        @tool(description="Test")
        async def my_tool(text: str, upstream: UpstreamClient):
            pass

        tools = get_custom_tools()
        schema = tools["my_tool"].parameters

        assert "text" in schema["properties"]
        assert "upstream" not in schema["properties"]

    def test_complex_types(self):
        """Handles complex type hints."""
        @tool(description="Test")
        async def my_tool(
            items: list[str],
            mapping: dict[str, int],
            optional_text: str | None = None
        ):
            pass

        tools = get_custom_tools()
        schema = tools["my_tool"].parameters

        assert schema["properties"]["items"]["type"] == "array"
        assert schema["properties"]["items"]["items"]["type"] == "string"
        assert schema["properties"]["mapping"]["type"] == "object"
