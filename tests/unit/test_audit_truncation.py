"""Tests for audit logging truncation logic."""

import pytest

from mcp_remixer.audit.truncation import (
    TRUNCATABLE_FIELDS,
    get_byte_length,
    truncate_content,
    truncate_string,
    truncate_value,
)


class TestTruncateString:
    """Tests for truncate_string function."""

    def test_no_truncation_needed(self):
        """String within limit should not be truncated."""
        result, was_truncated = truncate_string("hello", 10, "...")
        assert result == "hello"
        assert was_truncated is False

    def test_exact_limit(self):
        """String at exact limit should not be truncated."""
        result, was_truncated = truncate_string("hello", 5, "...")
        assert result == "hello"
        assert was_truncated is False

    def test_truncation_occurs(self):
        """String exceeding limit should be truncated."""
        result, was_truncated = truncate_string("hello world", 8, "...")
        assert was_truncated is True
        assert result.endswith("...")
        assert len(result.encode("utf-8")) <= 8

    def test_unicode_handling(self):
        """Multi-byte unicode characters should be handled correctly."""
        # Each emoji is 4 bytes in UTF-8
        text = "hello 🎉🎊🎁"
        result, was_truncated = truncate_string(text, 10, "...")
        assert was_truncated is True
        # Should not have partial unicode at boundary
        result.encode("utf-8")  # Should not raise

    def test_empty_string(self):
        """Empty string should not be truncated."""
        result, was_truncated = truncate_string("", 10, "...")
        assert result == ""
        assert was_truncated is False

    def test_marker_only_when_very_small_limit(self):
        """When limit is smaller than content but larger than marker."""
        result, was_truncated = truncate_string("hello world", 5, "...")
        assert was_truncated is True
        assert "..." in result


class TestGetByteLength:
    """Tests for get_byte_length function."""

    def test_ascii_string(self):
        """ASCII string length in bytes equals character count."""
        assert get_byte_length("hello") == 5

    def test_unicode_string(self):
        """Unicode strings have larger byte length."""
        # Each emoji is 4 bytes
        assert get_byte_length("🎉") == 4

    def test_dict(self):
        """Dict serialized to JSON."""
        result = get_byte_length({"key": "value"})
        assert result == len('{"key":"value"}')

    def test_list(self):
        """List serialized to JSON."""
        result = get_byte_length([1, 2, 3])
        assert result == len("[1,2,3]")


class TestTruncateValue:
    """Tests for truncate_value function."""

    def test_none_value(self):
        """None should return zeros and not truncated."""
        value, logged, original, truncated = truncate_value(None, 100, "...")
        assert value is None
        assert logged == 0
        assert original == 0
        assert truncated is False

    def test_string_no_truncation(self):
        """String within limit."""
        value, logged, original, truncated = truncate_value("hello", 100, "...")
        assert value == "hello"
        assert logged == 5
        assert original == 5
        assert truncated is False

    def test_string_truncation(self):
        """String exceeding limit."""
        value, logged, original, truncated = truncate_value(
            "hello world", 8, "..."
        )
        assert truncated is True
        assert logged <= 8
        assert original == 11

    def test_dict_truncation(self):
        """Dict serialized and truncated."""
        data = {"key": "a" * 100}
        value, logged, original, truncated = truncate_value(data, 20, "...")
        assert truncated is True
        assert logged <= 20
        assert original > 20

    def test_metadata_accuracy(self):
        """Verify logged_length and original_length are accurate."""
        text = "x" * 100
        value, logged, original, truncated = truncate_value(text, 50, "...")
        assert original == 100
        assert logged <= 50
        assert truncated is True


class TestTruncateContent:
    """Tests for truncate_content function."""

    def test_no_truncation_needed(self):
        """Content within limits should not be modified."""
        content = {"method": "test", "params": {"key": "value"}}
        result, any_truncated = truncate_content(content, 1000, "...")
        assert any_truncated is False
        assert result == content

    def test_truncate_text_field(self):
        """Text field should be truncated with inline metadata."""
        content = {
            "result": {
                "content": [{"type": "text", "text": "x" * 100}]
            }
        }
        result, any_truncated = truncate_content(content, 20, "...")
        assert any_truncated is True
        # Check inline metadata was added
        text_item = result["result"]["content"][0]
        assert "logged_length" in text_item
        assert "original_length" in text_item
        assert "truncated" in text_item
        assert text_item["truncated"] is True
        assert text_item["original_length"] == 100
        assert text_item["logged_length"] <= 20

    def test_truncate_arguments_field(self):
        """Arguments field (string) should be truncated."""
        content = {"params": {"arguments": "x" * 100}}
        result, any_truncated = truncate_content(content, 20, "...")
        assert any_truncated is True
        # Truncation metadata should be sibling to arguments
        assert "logged_length" in result["params"]
        assert result["params"]["truncated"] is True
        assert result["params"]["original_length"] == 100

    def test_multiple_fields_truncated(self):
        """Multiple truncated fields set single isTruncated."""
        content = {
            "result": {
                "content": [
                    {"type": "text", "text": "x" * 100},
                    {"type": "text", "text": "y" * 100},
                ]
            }
        }
        result, any_truncated = truncate_content(content, 20, "...")
        assert any_truncated is True
        # Both should be truncated
        assert result["result"]["content"][0]["truncated"] is True
        assert result["result"]["content"][1]["truncated"] is True

    def test_non_truncatable_fields_unchanged(self):
        """Fields not in truncatable list should not be modified."""
        content = {"method": "x" * 100, "id": 123}
        result, any_truncated = truncate_content(content, 20, "...")
        assert any_truncated is False
        assert result["method"] == "x" * 100  # Not truncated
        assert result["id"] == 123

    def test_nested_truncation(self):
        """Deeply nested fields should be truncated."""
        content = {
            "a": {
                "b": {
                    "c": {
                        "text": "x" * 100
                    }
                }
            }
        }
        result, any_truncated = truncate_content(content, 20, "...")
        assert any_truncated is True
        assert result["a"]["b"]["c"]["truncated"] is True

    def test_empty_content(self):
        """Empty content should return empty dict."""
        result, any_truncated = truncate_content({}, 100, "...")
        assert result == {}
        assert any_truncated is False

    def test_original_content_not_modified(self):
        """Original content dict should not be modified."""
        content = {"text": "x" * 100}
        original_text = content["text"]
        result, _ = truncate_content(content, 20, "...")
        assert content["text"] == original_text  # Original unchanged

    def test_exact_limit_no_truncation(self):
        """Value at exact limit should not be truncated."""
        content = {"text": "x" * 20}  # Exactly 20 bytes
        result, any_truncated = truncate_content(content, 20, "...")
        assert any_truncated is False

    def test_one_byte_less_triggers_truncation(self):
        """Value one byte over limit should be truncated."""
        content = {"text": "x" * 21}  # 21 bytes
        result, any_truncated = truncate_content(content, 20, "...")
        assert any_truncated is True

    def test_custom_truncatable_fields(self):
        """Custom truncatable fields should be respected."""
        content = {"custom_field": "x" * 100, "text": "y" * 100}
        result, any_truncated = truncate_content(
            content, 20, "...", truncatable_fields={"custom_field"}
        )
        assert any_truncated is True
        assert "truncated" in result  # custom_field was truncated
        # text should not be truncated since it's not in custom list
        assert result["text"] == "y" * 100
