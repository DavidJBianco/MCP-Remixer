"""Command-line interface for mcp-remixer."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from mcp_remixer import __version__
from mcp_remixer.exceptions import ConfigError, MCPRemixerError
from mcp_remixer.server import run_server

# Default config file name
DEFAULT_CONFIG = "mcp-remixer.yaml"


def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO

    # Log to stderr so stdout is clean for MCP protocol
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    # Set up root logger for mcp_remixer
    logger = logging.getLogger("mcp_remixer")
    logger.setLevel(level)
    logger.addHandler(handler)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="mcp-remixer",
        description="MCP proxy server that lets you add custom tools, hide existing ones, "
        "and aggregate multiple upstream servers.",
    )

    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help=f"Path to configuration file (default: ./{DEFAULT_CONFIG})",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser.parse_args(args)


def find_config(config_arg: Path | None) -> Path:
    """Find the configuration file.

    Args:
        config_arg: Config path from command line, or None

    Returns:
        Path to the configuration file

    Raises:
        ConfigError: If no configuration file is found
    """
    if config_arg is not None:
        if not config_arg.exists():
            raise ConfigError(f"Configuration file not found: {config_arg}")
        return config_arg.resolve()

    # Look for default config in current directory
    default_path = Path.cwd() / DEFAULT_CONFIG
    if default_path.exists():
        return default_path.resolve()

    raise ConfigError(
        f"No configuration file found. Create '{DEFAULT_CONFIG}' or use --config"
    )


def main(args: list[str] | None = None) -> int:
    """Main entry point for the CLI.

    Args:
        args: Command-line arguments (defaults to sys.argv)

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parsed = parse_args(args)

    setup_logging(parsed.verbose)
    logger = logging.getLogger("mcp_remixer")

    try:
        config_path = find_config(parsed.config)
        logger.info(f"Using configuration: {config_path}")

        asyncio.run(run_server(config_path))
        return 0

    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    except MCPRemixerError as e:
        logger.error(f"Error: {e}")
        return 1

    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
