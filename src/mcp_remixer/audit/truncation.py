"""Truncation logic for audit logging.

This module provides functions to truncate large content fields while
preserving length metadata inline with the truncated values.
"""

import json
from copy import deepcopy
from typing import Any


# Fields that should be considered for truncation (leaf string fields)
# Note: Only string values in these fields are truncated.
# Container fields like "result" and "content" are recursed into.
TRUNCATABLE_FIELDS = {"arguments", "data", "text"}


def truncate_string(
    value: str,
    max_length: int,
    marker: str,
) -> tuple[str, bool]:
    """Truncate a string if it exceeds max_length.

    Args:
        value: The string to truncate.
        max_length: Maximum length in bytes.
        marker: String to append when truncating.

    Returns:
        Tuple of (truncated_string, was_truncated).
    """
    encoded = value.encode("utf-8")
    if len(encoded) <= max_length:
        return value, False

    # Calculate how much space we have for actual content
    marker_bytes = marker.encode("utf-8")
    available = max_length - len(marker_bytes)

    if available <= 0:
        return marker, True

    # Truncate at byte boundary, being careful with UTF-8
    truncated_bytes = encoded[:available]

    # Decode, handling potential partial UTF-8 characters at the boundary
    truncated = truncated_bytes.decode("utf-8", errors="ignore")

    return truncated + marker, True


def get_byte_length(value: Any) -> int:
    """Get the byte length of a value when JSON serialized.

    Args:
        value: Any JSON-serializable value.

    Returns:
        Length in bytes of the JSON representation.
    """
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def truncate_value(
    value: Any,
    max_length: int,
    marker: str,
) -> tuple[Any, int, int, bool]:
    """Truncate a value if it exceeds max_length.

    For strings, truncates directly. For other types, serializes to JSON
    and truncates the string representation.

    Args:
        value: The value to truncate.
        max_length: Maximum length in bytes.
        marker: String to append when truncating.

    Returns:
        Tuple of (truncated_value, logged_length, original_length, was_truncated).
    """
    if value is None:
        return None, 0, 0, False

    original_length = get_byte_length(value)

    if original_length <= max_length:
        return value, original_length, original_length, False

    if isinstance(value, str):
        truncated, _ = truncate_string(value, max_length, marker)
        logged_length = len(truncated.encode("utf-8"))
        return truncated, logged_length, original_length, True

    # For non-strings, serialize to JSON and truncate the string
    serialized = json.dumps(value, separators=(",", ":"))
    truncated, _ = truncate_string(serialized, max_length, marker)
    logged_length = len(truncated.encode("utf-8"))
    return truncated, logged_length, original_length, True


def _truncate_dict_recursive(
    obj: dict[str, Any],
    max_length: int,
    marker: str,
    truncatable_fields: set[str],
) -> tuple[dict[str, Any], bool]:
    """Recursively truncate fields in a dictionary.

    When a truncatable field is found and truncated, adds inline metadata:
    - logged_length: actual bytes in the logged value
    - original_length: original bytes before truncation
    - truncated: True

    Args:
        obj: Dictionary to process.
        max_length: Maximum length for truncatable fields.
        marker: String to append when truncating.
        truncatable_fields: Set of field names to consider for truncation.

    Returns:
        Tuple of (processed_dict, any_truncated).
    """
    result = {}
    any_truncated = False

    for key, value in obj.items():
        if key in truncatable_fields:
            # Only truncate string values; recurse into containers
            if isinstance(value, str):
                truncated_value, logged_len, original_len, was_truncated = truncate_value(
                    value, max_length, marker
                )
                if was_truncated:
                    any_truncated = True
                    # Add truncation metadata as siblings
                    result[key] = truncated_value
                    result["logged_length"] = logged_len
                    result["original_length"] = original_len
                    result["truncated"] = True
                else:
                    result[key] = value
            elif isinstance(value, dict):
                # Recurse into dict even if key is truncatable
                processed, child_truncated = _truncate_dict_recursive(
                    value, max_length, marker, truncatable_fields
                )
                result[key] = processed
                if child_truncated:
                    any_truncated = True
            elif isinstance(value, list):
                # Recurse into list even if key is truncatable
                processed_list, list_truncated = _truncate_list_recursive(
                    value, max_length, marker, truncatable_fields
                )
                result[key] = processed_list
                if list_truncated:
                    any_truncated = True
            else:
                # Non-string, non-container truncatable field - truncate as JSON
                truncated_value, logged_len, original_len, was_truncated = truncate_value(
                    value, max_length, marker
                )
                if was_truncated:
                    any_truncated = True
                    result[key] = truncated_value
                    result["logged_length"] = logged_len
                    result["original_length"] = original_len
                    result["truncated"] = True
                else:
                    result[key] = value
        elif isinstance(value, dict):
            processed, child_truncated = _truncate_dict_recursive(
                value, max_length, marker, truncatable_fields
            )
            result[key] = processed
            if child_truncated:
                any_truncated = True
        elif isinstance(value, list):
            processed_list, list_truncated = _truncate_list_recursive(
                value, max_length, marker, truncatable_fields
            )
            result[key] = processed_list
            if list_truncated:
                any_truncated = True
        else:
            result[key] = value

    return result, any_truncated


def _truncate_list_recursive(
    items: list[Any],
    max_length: int,
    marker: str,
    truncatable_fields: set[str],
) -> tuple[list[Any], bool]:
    """Recursively truncate fields in list items.

    Args:
        items: List to process.
        max_length: Maximum length for truncatable fields.
        marker: String to append when truncating.
        truncatable_fields: Set of field names to consider for truncation.

    Returns:
        Tuple of (processed_list, any_truncated).
    """
    result = []
    any_truncated = False

    for item in items:
        if isinstance(item, dict):
            processed, child_truncated = _truncate_dict_recursive(
                item, max_length, marker, truncatable_fields
            )
            result.append(processed)
            if child_truncated:
                any_truncated = True
        elif isinstance(item, list):
            processed, child_truncated = _truncate_list_recursive(
                item, max_length, marker, truncatable_fields
            )
            result.append(processed)
            if child_truncated:
                any_truncated = True
        else:
            result.append(item)

    return result, any_truncated


def truncate_content(
    content: dict[str, Any],
    max_length: int,
    marker: str,
    truncatable_fields: set[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Truncate fields in content that exceed max_length.

    Truncation metadata (logged_length, original_length, truncated) is added
    inline as siblings to the truncated field.

    Args:
        content: The content dictionary to process.
        max_length: Maximum length for truncatable fields in bytes.
        marker: String to append when truncating.
        truncatable_fields: Set of field names to truncate. Defaults to
            TRUNCATABLE_FIELDS if not specified.

    Returns:
        Tuple of (processed_content, any_truncated).
    """
    if truncatable_fields is None:
        truncatable_fields = TRUNCATABLE_FIELDS

    # Deep copy to avoid modifying the original
    content_copy = deepcopy(content)

    return _truncate_dict_recursive(
        content_copy, max_length, marker, truncatable_fields
    )
