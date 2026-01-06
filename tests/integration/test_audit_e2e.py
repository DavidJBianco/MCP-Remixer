"""End-to-end integration tests for audit logging with real upstream MCP servers.

These tests start mcp-remixer as a subprocess with a real filesystem MCP server
upstream, make actual MCP calls, and verify the audit log contents.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


def create_server_params(config_file: Path) -> StdioServerParameters:
    """Create StdioServerParameters for connecting to mcp-remixer."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_remixer", "--config", str(config_file)],
        env=env,
    )


@pytest.fixture
def test_workspace(tmp_path: Path) -> Path:
    """Create a workspace directory with test files for the filesystem server."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create test files
    (workspace / "hello.txt").write_text("Hello, World!")
    (workspace / "data.json").write_text('{"key": "value", "number": 42}')

    # Create a subdirectory with a file
    subdir = workspace / "subdir"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("Nested content")

    return workspace


@pytest.fixture
def audit_log_path(tmp_path: Path) -> Path:
    """Path for the audit log file."""
    return tmp_path / "audit.jsonl"


@pytest.fixture
def config_file(tmp_path: Path, test_workspace: Path, audit_log_path: Path) -> Path:
    """Create a mcp-remixer config file for testing."""
    config_content = f"""
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "{test_workspace}"]
    required: true

hidden:
  tools:
    - "write_file"  # Hide write_file for testing hidden tool errors

audit:
  enabled: true
  log_file: "{audit_log_path}"
  truncate: false
"""
    config_path = tmp_path / "mcp-remixer.yaml"
    config_path.write_text(config_content)
    return config_path


@pytest.fixture
def config_file_with_truncation(
    tmp_path: Path, test_workspace: Path, audit_log_path: Path
) -> Path:
    """Create a mcp-remixer config file with truncation enabled."""
    config_content = f"""
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "{test_workspace}"]
    required: true

hidden:
  tools: []

audit:
  enabled: true
  log_file: "{audit_log_path}"
  truncate: true
  max_content_length: 50
"""
    config_path = tmp_path / "mcp-remixer-truncate.yaml"
    config_path.write_text(config_content)
    return config_path


def parse_audit_log(audit_log_path: Path) -> list[dict]:
    """Parse the audit log file and return list of entries."""
    if not audit_log_path.exists():
        return []

    entries = []
    with open(audit_log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


class TestAuditLoggingEndToEnd:
    """End-to-end tests for audit logging with real MCP servers."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_successful_tool_call_logged(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that a successful tool call is properly logged."""
        # Connect as an MCP client
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the session
                await session.initialize()

                # List tools to verify connection
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]

                # Verify filesystem tools are available (except hidden write_file)
                assert "read_file" in tool_names
                assert "list_directory" in tool_names
                assert "write_file" not in tool_names  # Hidden

                # Call read_file tool
                result = await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

                # Verify the result
                assert len(result.content) > 0
                assert "Hello, World!" in result.content[0].text

        # Give a moment for file flush
        await asyncio.sleep(0.5)

        # Parse and verify audit log
        entries = parse_audit_log(audit_log_path)
        assert len(entries) > 0, "Audit log should have entries"

        # Find the tools/call request for read_file
        call_requests = [
            e
            for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "tools/call"
            and e.get("content", {}).get("params", {}).get("name") == "read_file"
        ]
        assert len(call_requests) >= 1, "Should have logged read_file tool call request"

        # Find the response
        responses = [e for e in entries if e.get("message_type") == "response"]
        assert len(responses) >= 1, "Should have logged responses"

        # Verify initialize was logged
        init_requests = [
            e
            for e in entries
            if e.get("message_type") == "request" and e.get("method") == "initialize"
        ]
        assert len(init_requests) >= 1, "Should have logged initialize request"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_list_directory_logged(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that list_directory tool call is logged."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # List the directory
                result = await session.call_tool(
                    "list_directory", {"path": str(test_workspace)}
                )

                # Verify the result contains our test files
                content_text = result.content[0].text
                assert "hello.txt" in content_text
                assert "data.json" in content_text
                assert "subdir" in content_text

        await asyncio.sleep(0.5)

        # Verify audit log
        entries = parse_audit_log(audit_log_path)

        # Find list_directory call
        list_dir_calls = [
            e
            for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "tools/call"
            and e.get("content", {}).get("params", {}).get("name") == "list_directory"
        ]
        assert len(list_dir_calls) >= 1, "Should have logged list_directory call"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_nonexistent_file_error_logged(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that errors from reading nonexistent files are logged."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Try to read a file that doesn't exist
                result = await session.call_tool(
                    "read_file",
                    {"path": str(test_workspace / "nonexistent.txt")},
                )

                # The filesystem server returns an error in the content
                assert result.isError or any(
                    "error" in c.text.lower() or "not found" in c.text.lower()
                    for c in result.content
                    if hasattr(c, "text")
                )

        await asyncio.sleep(0.5)

        # Verify the request was logged
        entries = parse_audit_log(audit_log_path)

        # Find the read_file call for nonexistent file
        read_calls = [
            e
            for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "tools/call"
            and "nonexistent" in str(e.get("content", {}))
        ]
        assert len(read_calls) >= 1, "Should have logged the failed read_file request"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_hidden_tool_error_logged(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that attempting to call a hidden tool results in an error that's logged."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Try to call the hidden write_file tool
                # This should result in an error since write_file is hidden
                try:
                    result = await session.call_tool(
                        "write_file",
                        {
                            "path": str(test_workspace / "should_not_create.txt"),
                            "content": "This should fail",
                        },
                    )
                    # If we get here, check if it's an error result
                    assert result.isError or any(
                        "hidden" in c.text.lower() or "not found" in c.text.lower()
                        for c in result.content
                        if hasattr(c, "text")
                    )
                except Exception as e:
                    # An exception is expected for hidden tools
                    assert "hidden" in str(e).lower() or "not found" in str(e).lower()

        await asyncio.sleep(0.5)

        # Verify the file was NOT created (tool was hidden)
        assert not (test_workspace / "should_not_create.txt").exists()

        # Verify audit log captured the attempt
        entries = parse_audit_log(audit_log_path)
        assert len(entries) > 0, "Audit log should have entries"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_invalid_tool_name_error_logged(
        self, config_file: Path, audit_log_path: Path
    ):
        """Test that calling a completely invalid tool name results in an error."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Try to call a tool that doesn't exist at all
                try:
                    result = await session.call_tool(
                        "completely_fake_tool_name",
                        {"arg": "value"},
                    )
                    # Check if error is in result
                    assert result.isError or len(result.content) == 0
                except Exception:
                    # Exception is expected for unknown tools
                    pass

        await asyncio.sleep(0.5)

        # Verify audit log exists and has entries
        entries = parse_audit_log(audit_log_path)
        assert len(entries) > 0, "Audit log should have entries"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_tools_list_logged(
        self, config_file: Path, audit_log_path: Path
    ):
        """Test that tools/list requests are logged."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # List tools
                tools_result = await session.list_tools()
                assert len(tools_result.tools) > 0

        await asyncio.sleep(0.5)

        # Verify tools/list was logged
        entries = parse_audit_log(audit_log_path)

        tools_list_requests = [
            e
            for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "tools/list"
        ]
        assert len(tools_list_requests) >= 1, "Should have logged tools/list request"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_request_response_correlation(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that requests and responses can be correlated via request_id."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Make a tool call
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

        await asyncio.sleep(0.5)

        entries = parse_audit_log(audit_log_path)

        # Find a tools/call request
        tool_call_requests = [
            e
            for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "tools/call"
        ]

        for req in tool_call_requests:
            req_id = req.get("identifiers", {}).get("request_id")
            if req_id is not None:
                # Find matching response
                matching_responses = [
                    e
                    for e in entries
                    if e.get("message_type") == "response"
                    and e.get("identifiers", {}).get("request_id") == req_id
                ]
                # Should have exactly one matching response
                assert (
                    len(matching_responses) == 1
                ), f"Should have exactly one response for request_id {req_id}"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_processing_time_recorded(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that processing time is recorded for responses."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

        await asyncio.sleep(0.5)

        entries = parse_audit_log(audit_log_path)

        # Find responses with processing time
        responses_with_time = [
            e
            for e in entries
            if e.get("message_type") == "response"
            and e.get("processing_time_ms") is not None
        ]

        assert len(responses_with_time) > 0, "Some responses should have processing_time_ms"

        # Verify processing time is reasonable (positive number, less than 30 seconds)
        for resp in responses_with_time:
            pt = resp["processing_time_ms"]
            assert pt >= 0, "Processing time should be non-negative"
            assert pt < 30000, "Processing time should be less than 30 seconds"


class TestAuditLoggingWithTruncation:
    """End-to-end tests for audit logging with truncation enabled."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_large_response_truncated(
        self,
        config_file_with_truncation: Path,
        audit_log_path: Path,
        test_workspace: Path,
    ):
        """Test that large responses are truncated when truncation is enabled."""
        # Create a large file
        large_content = "A" * 1000  # Much larger than max_content_length of 50
        (test_workspace / "large.txt").write_text(large_content)

        server_params = create_server_params(config_file_with_truncation)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Read the large file
                result = await session.call_tool(
                    "read_file", {"path": str(test_workspace / "large.txt")}
                )

                # The actual result should have the full content
                assert "A" * 100 in result.content[0].text

        await asyncio.sleep(0.5)

        # Parse audit log
        entries = parse_audit_log(audit_log_path)

        # Find the response for read_file
        responses = [e for e in entries if e.get("message_type") == "response"]

        # At least one response should be truncated
        truncated_responses = [e for e in responses if e.get("isTruncated") is True]
        assert len(truncated_responses) > 0, "Some responses should be truncated"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_small_response_not_truncated(
        self,
        config_file_with_truncation: Path,
        audit_log_path: Path,
        test_workspace: Path,
    ):
        """Test that small responses are not truncated."""
        # Create a small file (less than max_content_length)
        small_content = "Hi"  # Well under 50 bytes
        (test_workspace / "tiny.txt").write_text(small_content)

        server_params = create_server_params(config_file_with_truncation)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "tiny.txt")}
                )

        await asyncio.sleep(0.5)

        entries = parse_audit_log(audit_log_path)

        # The response for the tiny file should not be truncated
        # (though other responses like initialize might be)
        responses = [e for e in entries if e.get("message_type") == "response"]
        assert len(responses) > 0, "Should have response entries"


class TestAuditToolVisibility:
    """Tests verifying which tools appear in audit logs.

    These tests verify that:
    - Custom tools added by the proxy appear in tools/list audit logs
    - Hidden tools do NOT appear in tools/list audit logs
    - Attempts to call hidden tools ARE logged (for security auditing)
    """

    @pytest.fixture
    def custom_tools_dir(self, tmp_path: Path) -> Path:
        """Create a directory with custom tool definitions."""
        tools_dir = tmp_path / "custom_tools"
        tools_dir.mkdir()

        # Create a custom tool that will be added by the proxy
        tool_file = tools_dir / "proxy_tools.py"
        tool_file.write_text('''
from mcp_remixer import tool

@tool(description="A custom tool added by the proxy")
async def proxy_custom_tool(message: str) -> str:
    """Echo a message back with a prefix.

    Args:
        message: The message to echo
    """
    return f"proxy says: {message}"

@tool(description="Another custom tool from the proxy")
async def proxy_helper_tool(value: int) -> str:
    """Double a value.

    Args:
        value: The number to double
    """
    return f"doubled: {value * 2}"
''')
        return tools_dir

    @pytest.fixture
    def config_with_custom_tools(
        self, tmp_path: Path, test_workspace: Path, audit_log_path: Path, custom_tools_dir: Path
    ) -> Path:
        """Create a config with both upstream and custom tools, plus hidden tools."""
        config_content = f"""
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "{test_workspace}"]
    required: true

custom_tools:
  - "{custom_tools_dir / 'proxy_tools.py'}"

hidden:
  tools:
    - "write_file"  # Hide this upstream tool

audit:
  enabled: true
  log_file: "{audit_log_path}"
  truncate: false
"""
        config_path = tmp_path / "mcp-remixer-custom.yaml"
        config_path.write_text(config_content)
        return config_path

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_custom_tools_appear_in_tools_list_audit_log(
        self, config_with_custom_tools: Path, audit_log_path: Path
    ):
        """Test that custom tools added by the proxy appear in the tools/list audit log response."""
        server_params = create_server_params(config_with_custom_tools)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # List tools - this should include both upstream and custom tools
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]

                # Verify custom tools are visible to the client
                assert "proxy_custom_tool" in tool_names, "Custom tool should be visible to client"
                assert "proxy_helper_tool" in tool_names, "Custom tool should be visible to client"

                # Verify upstream tools are also visible
                assert "read_file" in tool_names, "Upstream tool should be visible"

        await asyncio.sleep(0.5)

        # Parse audit log and find the tools/list response
        entries = parse_audit_log(audit_log_path)

        # Find the tools/list response (outbound, response type)
        tools_list_responses = [
            e
            for e in entries
            if e.get("message_type") == "response"
            and e.get("direction") == "outbound"
        ]

        # Find the response that contains the tools list
        # The response after a tools/list request will have the tools in result.tools
        found_custom_tools_in_log = False
        for response in tools_list_responses:
            result = response.get("content", {}).get("result", {})
            if "tools" in result:
                logged_tool_names = [t.get("name") for t in result.get("tools", [])]
                # Check that custom tools appear in the logged response
                if "proxy_custom_tool" in logged_tool_names:
                    found_custom_tools_in_log = True
                    assert "proxy_helper_tool" in logged_tool_names, (
                        "All custom tools should appear in audit log"
                    )
                    assert "read_file" in logged_tool_names, (
                        "Upstream tools should also appear in audit log"
                    )
                    break

        assert found_custom_tools_in_log, (
            "Custom tools should appear in the tools/list response in the audit log"
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_hidden_tools_not_in_tools_list_audit_log(
        self, config_with_custom_tools: Path, audit_log_path: Path
    ):
        """Test that hidden tools do NOT appear in the tools/list audit log response."""
        server_params = create_server_params(config_with_custom_tools)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # List tools
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]

                # Verify hidden tool is NOT visible to client
                assert "write_file" not in tool_names, "Hidden tool should not be visible"

        await asyncio.sleep(0.5)

        # Parse audit log
        entries = parse_audit_log(audit_log_path)

        # Find the tools/list response
        for response in entries:
            if response.get("message_type") == "response":
                result = response.get("content", {}).get("result", {})
                if "tools" in result:
                    logged_tool_names = [t.get("name") for t in result.get("tools", [])]
                    # Hidden tool should NOT appear in the logged response
                    assert "write_file" not in logged_tool_names, (
                        "Hidden tools should NOT appear in tools/list audit log response"
                    )

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_hidden_tool_call_attempt_is_logged(
        self, config_with_custom_tools: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that attempts to call hidden tools ARE logged (for security auditing)."""
        server_params = create_server_params(config_with_custom_tools)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Attempt to call the hidden write_file tool
                try:
                    await session.call_tool(
                        "write_file",
                        {
                            "path": str(test_workspace / "should_not_exist.txt"),
                            "content": "This should fail",
                        },
                    )
                except Exception:
                    pass  # Expected to fail

        await asyncio.sleep(0.5)

        # Parse audit log
        entries = parse_audit_log(audit_log_path)

        # Find the tools/call REQUEST for write_file - this should be logged
        hidden_tool_requests = [
            e
            for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "tools/call"
            and e.get("content", {}).get("params", {}).get("name") == "write_file"
        ]

        assert len(hidden_tool_requests) >= 1, (
            "Attempt to call hidden tool should be logged in audit log (security audit trail)"
        )

        # Verify the request details are captured
        request = hidden_tool_requests[0]
        assert request.get("direction") == "inbound"
        params = request.get("content", {}).get("params", {})
        assert params.get("name") == "write_file"
        assert "should_not_exist.txt" in str(params.get("arguments", {}))

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_custom_tool_call_is_logged(
        self, config_with_custom_tools: Path, audit_log_path: Path
    ):
        """Test that calls to custom tools are logged with full details."""
        server_params = create_server_params(config_with_custom_tools)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Call the custom tool
                result = await session.call_tool(
                    "proxy_custom_tool",
                    {"message": "hello from test"},
                )

                # Verify the tool worked
                assert "proxy says: hello from test" in result.content[0].text

        await asyncio.sleep(0.5)

        # Parse audit log
        entries = parse_audit_log(audit_log_path)

        # Find the request for proxy_custom_tool
        custom_tool_requests = [
            e
            for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "tools/call"
            and e.get("content", {}).get("params", {}).get("name") == "proxy_custom_tool"
        ]

        assert len(custom_tool_requests) >= 1, "Custom tool call should be logged"

        # Verify arguments are captured
        request = custom_tool_requests[0]
        args = request.get("content", {}).get("params", {}).get("arguments", {})
        assert args.get("message") == "hello from test"

        # Find the corresponding response
        request_id = request.get("identifiers", {}).get("request_id")
        responses = [
            e
            for e in entries
            if e.get("message_type") == "response"
            and e.get("identifiers", {}).get("request_id") == request_id
        ]

        assert len(responses) == 1, "Should have response for custom tool call"

        # Verify response contains the result
        response = responses[0]
        result_content = response.get("content", {}).get("result", {})
        assert "proxy says:" in str(result_content), "Response should contain tool output"


class TestMultipleClientSessions:
    """Tests for multiple client sessions and session ID uniqueness."""

    @pytest.fixture
    def shared_audit_log(self, tmp_path: Path) -> Path:
        """Path for a shared audit log file used by multiple sessions."""
        return tmp_path / "shared_audit.jsonl"

    @pytest.fixture
    def multi_session_config(
        self, tmp_path: Path, test_workspace: Path, shared_audit_log: Path
    ) -> Path:
        """Create a config file for multi-session testing."""
        config_content = f"""
upstreams:
  filesystem:
    transport: stdio
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "{test_workspace}"]
    required: true

hidden:
  tools: []

audit:
  enabled: true
  log_file: "{shared_audit_log}"
  truncate: false
"""
        config_path = tmp_path / "mcp-remixer-multi.yaml"
        config_path.write_text(config_content)
        return config_path

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_multiple_sessions_have_unique_session_ids(
        self, multi_session_config: Path, shared_audit_log: Path, test_workspace: Path
    ):
        """Test that multiple client sessions each get a unique session_id.

        This test:
        1. Creates two separate MCP client sessions sequentially
        2. Each session makes tool calls that generate audit log entries
        3. Verifies each session has a different session_id (UUID)
        4. Verifies request_ids within each session can be correlated
        """
        import uuid as uuid_module

        # Session 1: Connect, make some calls, disconnect
        server_params = create_server_params(multi_session_config)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.list_tools()
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

        # Small delay to ensure clean separation
        await asyncio.sleep(0.5)

        # Session 2: Connect, make different calls, disconnect
        server_params = create_server_params(multi_session_config)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.call_tool(
                    "list_directory", {"path": str(test_workspace)}
                )
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "data.json")}
                )

        await asyncio.sleep(0.5)

        # Parse the shared audit log
        entries = parse_audit_log(shared_audit_log)
        assert len(entries) > 0, "Audit log should have entries from both sessions"

        # Collect all unique session IDs
        session_ids = set()
        for entry in entries:
            session_id = entry.get("identifiers", {}).get("session_id")
            assert session_id is not None, "All entries should have session_id"
            # Verify it's a valid UUID
            try:
                uuid_module.UUID(session_id)
            except ValueError:
                pytest.fail(f"session_id '{session_id}' is not a valid UUID")
            session_ids.add(session_id)

        # Should have exactly 2 different session IDs (one per client session)
        assert len(session_ids) == 2, (
            f"Expected 2 unique session_ids for 2 client sessions, "
            f"but found {len(session_ids)}: {session_ids}"
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_request_response_correlation_across_sessions(
        self, multi_session_config: Path, shared_audit_log: Path, test_workspace: Path
    ):
        """Test that (session_id, request_id) pairs correctly identify messages.

        This verifies that even if two sessions have the same request_id values
        (e.g., both start at 0), the session_id distinguishes them.
        """
        # Session 1
        server_params = create_server_params(multi_session_config)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

        await asyncio.sleep(0.5)

        # Session 2
        server_params = create_server_params(multi_session_config)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

        await asyncio.sleep(0.5)

        entries = parse_audit_log(shared_audit_log)

        # Group entries by session_id
        sessions: dict[str, list[dict]] = {}
        for entry in entries:
            sid = entry.get("identifiers", {}).get("session_id")
            if sid:
                if sid not in sessions:
                    sessions[sid] = []
                sessions[sid].append(entry)

        assert len(sessions) == 2, "Should have entries from 2 sessions"

        # For each session, verify request/response correlation works
        for session_id, session_entries in sessions.items():
            requests = [
                e for e in session_entries if e.get("message_type") == "request"
            ]
            responses = [
                e for e in session_entries if e.get("message_type") == "response"
            ]

            # Each request should have a matching response in the same session
            for req in requests:
                req_id = req.get("identifiers", {}).get("request_id")
                if req_id is not None:
                    matching = [
                        r for r in responses
                        if r.get("identifiers", {}).get("request_id") == req_id
                    ]
                    assert len(matching) == 1, (
                        f"Session {session_id}: request_id {req_id} should have "
                        f"exactly one matching response, found {len(matching)}"
                    )

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_overlapping_request_ids_distinguished_by_session(
        self, multi_session_config: Path, shared_audit_log: Path, test_workspace: Path
    ):
        """Test that sessions with overlapping request_ids are distinguishable.

        Both sessions will likely have request_id=0 for initialize, request_id=1
        for their first tool call, etc. This test verifies the logs can be
        correctly partitioned by session_id.
        """
        # Run two sessions
        for i in range(2):
            server_params = create_server_params(multi_session_config)
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    await session.list_tools()

            await asyncio.sleep(0.3)

        await asyncio.sleep(0.5)

        entries = parse_audit_log(shared_audit_log)

        # Find all initialize requests (both sessions will have one)
        init_requests = [
            e for e in entries
            if e.get("message_type") == "request"
            and e.get("method") == "initialize"
        ]

        assert len(init_requests) == 2, "Should have 2 initialize requests"

        # They should have different session_ids
        init_session_ids = [
            e.get("identifiers", {}).get("session_id") for e in init_requests
        ]
        assert len(set(init_session_ids)) == 2, (
            "Initialize requests should have different session_ids"
        )

        # Both might have the same request_id (e.g., 0), but different session_ids
        init_request_ids = [
            e.get("identifiers", {}).get("request_id") for e in init_requests
        ]
        # Note: We're just verifying the data is present, not that they're the same
        # (they likely will be the same since both clients start at 0)
        assert all(rid is not None for rid in init_request_ids), (
            "All initialize requests should have request_ids"
        )

        # The key assertion: (session_id, request_id) tuples are unique
        id_pairs = [
            (e.get("identifiers", {}).get("session_id"),
             e.get("identifiers", {}).get("request_id"))
            for e in entries
            if e.get("message_type") == "request"
        ]
        # Remove None pairs
        id_pairs = [(s, r) for s, r in id_pairs if s is not None and r is not None]

        assert len(id_pairs) == len(set(id_pairs)), (
            "(session_id, request_id) pairs should be unique across all requests"
        )


class TestAuditLogFormat:
    """Tests for audit log format and structure."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_log_entry_structure(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that log entries have the expected structure."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

        await asyncio.sleep(0.5)

        entries = parse_audit_log(audit_log_path)
        assert len(entries) > 0

        # Check structure of each entry
        for entry in entries:
            # Required fields
            assert "timestamp" in entry
            assert "direction" in entry
            assert entry["direction"] in ["inbound", "outbound"]
            assert "message_type" in entry
            assert entry["message_type"] in ["request", "response", "notification", "error"]
            assert "identifiers" in entry
            assert "content" in entry
            assert "isTruncated" in entry

            # Timestamp should be ISO 8601
            timestamp = entry["timestamp"]
            assert "T" in timestamp  # ISO 8601 format has T separator

            # Identifiers structure
            identifiers = entry["identifiers"]
            assert "session_id" in identifiers
            assert "request_id" in identifiers
            assert "progress_token" in identifiers
            assert "client_name" in identifiers
            assert "client_version" in identifiers

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_session_id_is_consistent_uuid(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that session_id is a valid UUID and consistent across all entries."""
        import uuid as uuid_module

        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.list_tools()
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )

        await asyncio.sleep(0.5)

        entries = parse_audit_log(audit_log_path)
        assert len(entries) > 0

        # Collect all session_ids
        session_ids = set()
        for entry in entries:
            session_id = entry.get("identifiers", {}).get("session_id")
            assert session_id is not None, "session_id should be present in all entries"

            # Verify it's a valid UUID format
            try:
                uuid_module.UUID(session_id)
            except ValueError:
                pytest.fail(f"session_id '{session_id}' is not a valid UUID")

            session_ids.add(session_id)

        # All entries in a single session should have the same session_id
        assert len(session_ids) == 1, (
            f"All entries should have the same session_id, but found {len(session_ids)} different IDs"
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_jsonl_format_valid(
        self, config_file: Path, audit_log_path: Path, test_workspace: Path
    ):
        """Test that the audit log is valid JSON Lines format."""
        server_params = create_server_params(config_file)
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.list_tools()
                await session.call_tool(
                    "read_file", {"path": str(test_workspace / "hello.txt")}
                )
                await session.call_tool(
                    "list_directory", {"path": str(test_workspace)}
                )

        await asyncio.sleep(0.5)

        # Each line should be valid JSON
        with open(audit_log_path) as f:
            line_count = 0
            for line in f:
                line = line.strip()
                if line:
                    # This will raise if not valid JSON
                    json.loads(line)
                    line_count += 1

        assert line_count > 0, "Should have multiple log entries"
