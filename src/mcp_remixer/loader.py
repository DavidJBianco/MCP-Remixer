"""Custom tool loading from Python modules."""

import importlib.util
import logging
import sys
from pathlib import Path

from mcp_remixer.exceptions import ConfigError
from mcp_remixer.tool import ToolDefinition, clear_custom_tools, get_custom_tools

logger = logging.getLogger(__name__)


def load_custom_tools(tool_paths: list[Path]) -> dict[str, ToolDefinition]:
    """Load custom tools from Python module files.

    Args:
        tool_paths: List of paths to Python files containing @tool decorated functions

    Returns:
        Dictionary of tool name -> ToolDefinition

    Raises:
        ConfigError: If a module fails to load
    """
    # Clear any previously registered tools
    clear_custom_tools()

    for path in tool_paths:
        if not path.exists():
            raise ConfigError(f"Custom tool module not found: {path}")

        if not path.suffix == ".py":
            raise ConfigError(f"Custom tool module must be a .py file: {path}")

        try:
            # Create a unique module name based on the path
            module_name = f"mcp_remixer_custom_{path.stem}_{id(path)}"

            # Load the module
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ConfigError(f"Could not load module spec for: {path}")

            module = importlib.util.module_from_spec(spec)

            # Add to sys.modules before executing (allows relative imports within the module)
            sys.modules[module_name] = module

            # Execute the module (this triggers @tool decorators)
            spec.loader.exec_module(module)

            logger.info(f"Loaded custom tools from: {path}")

        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(f"Error loading custom tool module '{path}': {e}")

    # Return all registered tools
    return get_custom_tools()
