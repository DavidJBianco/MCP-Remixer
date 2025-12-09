"""Tests for custom tool loading."""

import pytest
from pathlib import Path

from mcp_remixer.loader import load_custom_tools
from mcp_remixer.exceptions import ConfigError
from mcp_remixer.tool import clear_custom_tools


class TestLoadCustomTools:
    """Tests for load_custom_tools function."""

    def test_load_simple_tool_module(self, tmp_path: Path):
        """Loads a simple tool module."""
        tool_file = tmp_path / "simple_tools.py"
        tool_file.write_text("""
from mcp_remixer import tool

@tool(description="Say hello")
async def hello(name: str):
    return f"Hello, {name}!"
""")

        tools = load_custom_tools([tool_file])

        assert "hello" in tools
        assert tools["hello"].description == "Say hello"

    def test_load_multiple_tools_from_module(self, tmp_path: Path):
        """Loads multiple tools from a single module."""
        tool_file = tmp_path / "multi_tools.py"
        tool_file.write_text("""
from mcp_remixer import tool

@tool(description="Tool 1")
async def tool_one():
    pass

@tool(description="Tool 2")
async def tool_two():
    pass

@tool(description="Tool 3")
def tool_three():
    pass
""")

        tools = load_custom_tools([tool_file])

        assert len(tools) == 3
        assert "tool_one" in tools
        assert "tool_two" in tools
        assert "tool_three" in tools

    def test_load_multiple_modules(self, tmp_path: Path):
        """Loads tools from multiple modules."""
        tool_file1 = tmp_path / "tools1.py"
        tool_file1.write_text("""
from mcp_remixer import tool

@tool(description="From module 1")
async def from_mod1():
    pass
""")

        tool_file2 = tmp_path / "tools2.py"
        tool_file2.write_text("""
from mcp_remixer import tool

@tool(description="From module 2")
async def from_mod2():
    pass
""")

        tools = load_custom_tools([tool_file1, tool_file2])

        assert "from_mod1" in tools
        assert "from_mod2" in tools

    def test_missing_module_raises_error(self, tmp_path: Path):
        """Raises error for missing module file."""
        missing_file = tmp_path / "nonexistent.py"

        with pytest.raises(ConfigError) as exc_info:
            load_custom_tools([missing_file])

        assert "not found" in str(exc_info.value)

    def test_invalid_file_extension_raises_error(self, tmp_path: Path):
        """Raises error for non-.py file."""
        invalid_file = tmp_path / "tools.txt"
        invalid_file.write_text("not python")

        with pytest.raises(ConfigError) as exc_info:
            load_custom_tools([invalid_file])

        assert ".py" in str(exc_info.value)

    def test_syntax_error_raises_config_error(self, tmp_path: Path):
        """Raises ConfigError for syntax errors in module."""
        tool_file = tmp_path / "bad_syntax.py"
        tool_file.write_text("""
def broken(
    # missing closing paren
""")

        with pytest.raises(ConfigError) as exc_info:
            load_custom_tools([tool_file])

        assert "Error loading" in str(exc_info.value)

    def test_import_error_raises_config_error(self, tmp_path: Path):
        """Raises ConfigError for import errors in module."""
        tool_file = tmp_path / "bad_import.py"
        tool_file.write_text("""
from nonexistent_package import something
""")

        with pytest.raises(ConfigError) as exc_info:
            load_custom_tools([tool_file])

        assert "Error loading" in str(exc_info.value)

    def test_empty_module_returns_empty_dict(self, tmp_path: Path):
        """Empty module returns empty dict."""
        tool_file = tmp_path / "empty.py"
        tool_file.write_text("# Just a comment")

        tools = load_custom_tools([tool_file])

        assert tools == {}

    def test_clears_previous_tools(self, tmp_path: Path):
        """Clears previously registered tools before loading."""
        tool_file1 = tmp_path / "tools1.py"
        tool_file1.write_text("""
from mcp_remixer import tool

@tool(description="First")
async def first_tool():
    pass
""")

        tool_file2 = tmp_path / "tools2.py"
        tool_file2.write_text("""
from mcp_remixer import tool

@tool(description="Second")
async def second_tool():
    pass
""")

        # Load first module
        tools1 = load_custom_tools([tool_file1])
        assert "first_tool" in tools1

        # Load second module - should clear first
        tools2 = load_custom_tools([tool_file2])
        assert "second_tool" in tools2
        assert "first_tool" not in tools2

    def test_tool_with_explicit_schema(self, tmp_path: Path):
        """Loads tool with explicit parameter schema."""
        tool_file = tmp_path / "schema_tool.py"
        tool_file.write_text("""
from mcp_remixer import tool

@tool(
    description="Search",
    parameters={
        "query": {"type": "string", "description": "Search query"},
        "mode": {"type": "string", "enum": ["fast", "deep"]}
    }
)
async def search(query: str, mode: str):
    pass
""")

        tools = load_custom_tools([tool_file])

        assert "search" in tools
        schema = tools["search"].parameters
        assert "mode" in schema["properties"]
        assert schema["properties"]["mode"]["enum"] == ["fast", "deep"]

    def test_empty_paths_list(self):
        """Empty paths list returns empty dict."""
        tools = load_custom_tools([])
        assert tools == {}
