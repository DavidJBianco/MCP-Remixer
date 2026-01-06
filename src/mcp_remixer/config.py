"""Configuration loading and validation for mcp-remixer."""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from mcp_remixer.audit.config import AuditConfig
from mcp_remixer.exceptions import ConfigError

logger = logging.getLogger(__name__)


@dataclass
class StdioUpstreamConfig:
    """Configuration for a stdio-based upstream server."""

    name: str
    transport: str  # "stdio"
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    required: bool = False
    tool_prefix: str = ""


@dataclass
class SSEUpstreamConfig:
    """Configuration for an SSE-based upstream server."""

    name: str
    transport: str  # "sse"
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    required: bool = False
    tool_prefix: str = ""
    verify_ssl: bool = True


@dataclass
class HTTPUpstreamConfig:
    """Configuration for an HTTP-based upstream server using Streamable HTTP."""

    name: str
    transport: str  # "http"
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    read_timeout: float = 300.0
    required: bool = False
    tool_prefix: str = ""
    verify_ssl: bool = True


UpstreamConfig = StdioUpstreamConfig | SSEUpstreamConfig | HTTPUpstreamConfig


@dataclass
class HiddenConfig:
    """Configuration for hidden items."""

    tools: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)


@dataclass
class Config:
    """Root configuration object."""

    upstreams: dict[str, UpstreamConfig] = field(default_factory=dict)
    hidden: HiddenConfig = field(default_factory=HiddenConfig)
    custom_tools: list[Path] = field(default_factory=list)
    config_dir: Path = field(default_factory=lambda: Path.cwd())
    audit: AuditConfig = field(default_factory=AuditConfig)


def _expand_env_vars(value: str) -> str:
    """Expand ${VAR} patterns in a string with environment variable values."""
    pattern = re.compile(r"\$\{([^}]+)\}")

    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise ConfigError(f"Environment variable '{var_name}' is not set")
        return env_value

    return pattern.sub(replace, value)


def _expand_env_in_dict(d: dict) -> dict:
    """Recursively expand environment variables in a dictionary."""
    result = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = _expand_env_vars(value)
        elif isinstance(value, dict):
            result[key] = _expand_env_in_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _expand_env_vars(item) if isinstance(item, str) else item for item in value
            ]
        else:
            result[key] = value
    return result


def _parse_upstream(name: str, data: dict) -> UpstreamConfig:
    """Parse a single upstream configuration."""
    transport = data.get("transport")
    if not transport:
        raise ConfigError(f"Upstream '{name}' missing required field 'transport'")

    # Expand environment variables
    data = _expand_env_in_dict(data)

    if transport == "stdio":
        command = data.get("command")
        if not command:
            raise ConfigError(f"Upstream '{name}' with stdio transport missing 'command'")

        return StdioUpstreamConfig(
            name=name,
            transport="stdio",
            command=command,
            args=data.get("args", []),
            env=data.get("env", {}),
            required=data.get("required", False),
            tool_prefix=data.get("tool_prefix", ""),
        )

    elif transport == "sse":
        url = data.get("url")
        if not url:
            raise ConfigError(f"Upstream '{name}' with sse transport missing 'url'")

        return SSEUpstreamConfig(
            name=name,
            transport="sse",
            url=url,
            headers=data.get("headers", {}),
            required=data.get("required", False),
            tool_prefix=data.get("tool_prefix", ""),
            verify_ssl=data.get("verify_ssl", True),
        )

    elif transport == "http":
        url = data.get("url")
        if not url:
            raise ConfigError(f"Upstream '{name}' with http transport missing 'url'")

        return HTTPUpstreamConfig(
            name=name,
            transport="http",
            url=url,
            headers=data.get("headers", {}),
            timeout=float(data.get("timeout", 30.0)),
            read_timeout=float(data.get("read_timeout", 300.0)),
            required=data.get("required", False),
            tool_prefix=data.get("tool_prefix", ""),
            verify_ssl=data.get("verify_ssl", True),
        )

    else:
        raise ConfigError(f"Upstream '{name}' has invalid transport: '{transport}'")


def _parse_audit(data: dict, config_dir: Path) -> AuditConfig:
    """Parse audit logging configuration.

    Args:
        data: The raw audit configuration data.
        config_dir: The configuration file directory for resolving relative paths.

    Returns:
        Parsed AuditConfig object.
    """
    enabled = data.get("enabled", False)
    truncate = data.get("truncate", False)
    max_content_length = data.get("max_content_length", 1024)

    # Warn if max_content_length is set but truncate is false
    if "max_content_length" in data and not truncate:
        logger.warning(
            "audit.max_content_length is set but audit.truncate is false; "
            "max_content_length will be ignored"
        )

    # Parse log_file path
    log_file = None
    if "log_file" in data:
        log_file_str = data["log_file"]
        if isinstance(log_file_str, str):
            # Expand environment variables
            log_file_str = _expand_env_vars(log_file_str)
            log_file = Path(log_file_str)
            # Resolve relative paths against config directory
            if not log_file.is_absolute():
                log_file = config_dir / log_file
            log_file = log_file.resolve()

    # Validate: if enabled, log_file should be set
    if enabled and not log_file:
        logger.warning(
            "audit.enabled is true but audit.log_file is not set; "
            "audit logging will not work"
        )

    return AuditConfig(
        enabled=enabled,
        log_file=log_file,
        truncate=truncate,
        max_content_length=int(max_content_length),
        truncation_marker=data.get("truncation_marker", "...[TRUNCATED]"),
        log_requests=data.get("log_requests", True),
        log_responses=data.get("log_responses", True),
        log_notifications=data.get("log_notifications", True),
        log_errors=data.get("log_errors", True),
        pretty_print=data.get("pretty_print", False),
    )


def _find_env_files(config_dir: Path) -> list[Path]:
    """Find .env files to load, in priority order (lowest to highest)."""
    env_files = []
    cwd = Path.cwd()

    # Check current working directory
    cwd_env = cwd / ".env"
    if cwd_env.exists() and cwd_env.is_file():
        env_files.append(cwd_env)

    # Check config file directory (higher priority)
    if config_dir != cwd:
        config_dir_env = config_dir / ".env"
        if config_dir_env.exists() and config_dir_env.is_file():
            env_files.append(config_dir_env)

    return env_files


def load_config(config_path: Path) -> Config:
    """Load configuration from a YAML file.

    Args:
        config_path: Path to the configuration file.

    Returns:
        Parsed Config object.

    Raises:
        ConfigError: If the configuration is invalid.
    """
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    config_dir = config_path.parent.resolve()

    # Load .env files (cwd first, then config dir - later takes precedence)
    env_files = _find_env_files(config_dir)
    if env_files:
        for env_file in env_files:
            logger.debug(f"Loading environment from: {env_file}")
            load_dotenv(env_file, override=True)
    else:
        logger.debug("No .env files found")

    # Parse YAML
    try:
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in configuration file: {e}")

    if raw_config is None:
        raw_config = {}

    # Parse upstreams
    upstreams = {}
    raw_upstreams = raw_config.get("upstreams", {})
    if not isinstance(raw_upstreams, dict):
        raise ConfigError("'upstreams' must be a mapping")

    logger.debug(f"Found {len(raw_upstreams)} upstream(s) in config")
    for name, upstream_data in raw_upstreams.items():
        if not isinstance(upstream_data, dict):
            raise ConfigError(f"Upstream '{name}' must be a mapping")
        logger.debug(f"Parsing upstream '{name}' with transport '{upstream_data.get('transport')}'")
        upstreams[name] = _parse_upstream(name, upstream_data)

    # Parse hidden items
    raw_hidden = raw_config.get("hidden", {})
    if not isinstance(raw_hidden, dict):
        raise ConfigError("'hidden' must be a mapping")

    hidden = HiddenConfig(
        tools=raw_hidden.get("tools", []),
        prompts=raw_hidden.get("prompts", []),
        resources=raw_hidden.get("resources", []),
    )

    # Parse custom tools paths
    raw_custom_tools = raw_config.get("custom_tools", [])
    if not isinstance(raw_custom_tools, list):
        raise ConfigError("'custom_tools' must be a list")

    custom_tools = []
    for tool_path in raw_custom_tools:
        if not isinstance(tool_path, str):
            raise ConfigError(f"Custom tool path must be a string: {tool_path}")
        path = Path(tool_path)
        # Resolve relative paths against config directory
        if not path.is_absolute():
            path = config_dir / path
        custom_tools.append(path.resolve())

    # Parse audit configuration
    raw_audit = raw_config.get("audit", {})
    if not isinstance(raw_audit, dict):
        raise ConfigError("'audit' must be a mapping")

    audit = _parse_audit(raw_audit, config_dir)

    return Config(
        upstreams=upstreams,
        hidden=hidden,
        custom_tools=custom_tools,
        config_dir=config_dir,
        audit=audit,
    )
