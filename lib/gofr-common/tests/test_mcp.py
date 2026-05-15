"""Tests for MCP response utilities.

Tests cover:
1. JSON text formatting
2. Success/error response creation
3. Validation error formatting
4. MCPResponseBuilder functionality
5. Exception to response conversion
"""

import json
from typing import Sequence
from unittest.mock import MagicMock

from mcp.types import TextContent

from gofr_common.exceptions import GofrError, ValidationError
from gofr_common.mcp import (
    MCPResponseBuilder,
    error_response,
    format_validation_error,
    json_text,
    success_response,
)


def get_text(content: Sequence) -> str:
    """Helper to extract text from MCP content, with type assertion."""
    item = content[0]
    assert isinstance(item, TextContent), f"Expected TextContent, got {type(item)}"
    return item.text


class TestJsonText:
    """Tests for json_text function."""

    def test_basic_dict(self):
        """Test basic dictionary serialization."""
        data = {"key": "value", "number": 42}
        result = json_text(data)

        assert isinstance(result, TextContent)
        assert result.type == "text"

        parsed = json.loads(result.text)
        assert parsed == data

    def test_nested_dict(self):
        """Test nested dictionary serialization."""
        data = {"outer": {"inner": {"deep": "value"}}}
        result = json_text(data)

        parsed = json.loads(result.text)
        assert parsed["outer"]["inner"]["deep"] == "value"

    def test_with_list(self):
        """Test dictionary with list values."""
        data = {"items": [1, 2, 3], "names": ["a", "b"]}
        result = json_text(data)

        parsed = json.loads(result.text)
        assert parsed["items"] == [1, 2, 3]

    def test_indent_default(self):
        """Test default indentation is 2 spaces."""
        data = {"key": "value"}
        result = json_text(data)

        # Check for 2-space indentation
        assert '  "key"' in result.text

    def test_custom_indent(self):
        """Test custom indentation."""
        data = {"key": "value"}
        result = json_text(data, indent=4)

        # Check for 4-space indentation
        assert '    "key"' in result.text

    def test_pydantic_model_serialization(self):
        """Test that Pydantic models are serialized via model_dump."""
        mock_model = MagicMock()
        mock_model.model_dump.return_value = {"field": "value"}

        data = {"model": mock_model}
        result = json_text(data)

        parsed = json.loads(result.text)
        assert parsed["model"]["field"] == "value"

    def test_object_with_dict_serialization(self):
        """Test that objects with __dict__ are serialized."""
        class SimpleObj:
            def __init__(self):
                self.attr = "test"

        obj = SimpleObj()
        data = {"obj": obj}
        result = json_text(data)

        parsed = json.loads(result.text)
        assert parsed["obj"]["attr"] == "test"


class TestSuccessResponse:
    """Tests for success_response function."""

    def test_basic_success(self):
        """Test basic success response."""
        result = success_response({"result": "ok"})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

        parsed = json.loads(get_text(result))
        assert parsed["status"] == "success"
        assert parsed["data"]["result"] == "ok"

    def test_success_with_message(self):
        """Test success response with message."""
        result = success_response({"count": 5}, message="Found 5 items")

        parsed = json.loads(get_text(result))
        assert parsed["status"] == "success"
        assert parsed["message"] == "Found 5 items"
        assert parsed["data"]["count"] == 5

    def test_success_without_message(self):
        """Test success response has no message key when not provided."""
        result = success_response("simple data")

        parsed = json.loads(get_text(result))
        assert "message" not in parsed

    def test_success_with_various_data_types(self):
        """Test success with different data types."""
        # List
        result = success_response([1, 2, 3])
        parsed = json.loads(get_text(result))
        assert parsed["data"] == [1, 2, 3]

        # String
        result = success_response("text data")
        parsed = json.loads(get_text(result))
        assert parsed["data"] == "text data"

        # None
        result = success_response(None)
        parsed = json.loads(get_text(result))
        assert parsed["data"] is None


class TestErrorResponse:
    """Tests for error_response function."""

    def test_basic_error(self):
        """Test basic error response."""
        result = error_response("TEST_ERROR", "Something went wrong")

        assert len(result) == 1
        parsed = json.loads(get_text(result))

        assert parsed["status"] == "error"
        assert parsed["error_code"] == "TEST_ERROR"
        assert parsed["message"] == "Something went wrong"

    def test_error_with_recovery(self):
        """Test error with recovery strategy."""
        result = error_response(
            "INVALID_URL",
            "URL is malformed",
            recovery_strategy="Check the URL format",
        )

        parsed = json.loads(get_text(result))
        assert parsed["recovery_strategy"] == "Check the URL format"

    def test_error_with_details(self):
        """Test error with details."""
        result = error_response(
            "NOT_FOUND",
            "Resource not found",
            details={"resource_id": "abc123", "type": "template"},
        )

        parsed = json.loads(get_text(result))
        assert parsed["details"]["resource_id"] == "abc123"
        assert parsed["details"]["type"] == "template"

    def test_error_without_optional_fields(self):
        """Test error response doesn't include optional fields when not provided."""
        result = error_response("ERROR", "Message")

        parsed = json.loads(get_text(result))
        assert "recovery_strategy" not in parsed
        assert "details" not in parsed


class TestFormatValidationError:
    """Tests for format_validation_error function."""

    def test_missing_field_error(self):
        """Test formatting of missing field errors."""
        errors = [
            {"type": "missing", "loc": ("name",), "msg": "Field required"},
            {"type": "missing", "loc": ("value",), "msg": "Field required"},
        ]
        result = format_validation_error(errors)

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "VALIDATION_ERROR"
        assert "name" in parsed["message"]
        assert "value" in parsed["message"]
        assert "name" in parsed["recovery_strategy"]

    def test_other_validation_error(self):
        """Test formatting of non-missing validation errors."""
        errors = [
            {"type": "type_error", "loc": ("count",), "msg": "Input should be integer"},
        ]
        result = format_validation_error(errors)

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "VALIDATION_ERROR"
        assert "validation failed" in parsed["message"].lower()

    def test_with_context(self):
        """Test validation error with context."""
        errors = [{"type": "missing", "loc": ("field",), "msg": "required"}]
        result = format_validation_error(errors, context="Creating document session")

        parsed = json.loads(get_text(result))
        assert parsed["details"]["context"] == "Creating document session"

    def test_errors_in_details(self):
        """Test that raw errors are included in details."""
        errors = [{"type": "missing", "loc": ("x",), "msg": "required"}]
        result = format_validation_error(errors)

        parsed = json.loads(get_text(result))
        assert "validation_errors" in parsed["details"]
        assert len(parsed["details"]["validation_errors"]) == 1


class TestMCPResponseBuilder:
    """Tests for MCPResponseBuilder class."""

    def test_default_recovery_strategies(self):
        """Test default recovery strategies are set."""
        builder = MCPResponseBuilder()

        assert "VALIDATION_ERROR" in builder._recovery_strategies
        assert "AUTH_REQUIRED" in builder._recovery_strategies
        assert "NOT_FOUND" in builder._recovery_strategies

    def test_set_recovery_strategy(self):
        """Test setting a custom recovery strategy."""
        builder = MCPResponseBuilder()
        builder.set_recovery_strategy("CUSTOM_ERROR", "Do this to fix it")

        assert builder.get_recovery_strategy("CUSTOM_ERROR") == "Do this to fix it"

    def test_set_recovery_strategies_bulk(self):
        """Test setting multiple strategies at once."""
        builder = MCPResponseBuilder()
        builder.set_recovery_strategies({
            "ERROR_A": "Fix A",
            "ERROR_B": "Fix B",
        })

        assert builder.get_recovery_strategy("ERROR_A") == "Fix A"
        assert builder.get_recovery_strategy("ERROR_B") == "Fix B"

    def test_get_recovery_strategy_default(self):
        """Test default recovery strategy for unknown codes."""
        builder = MCPResponseBuilder()
        strategy = builder.get_recovery_strategy("UNKNOWN_CODE")

        assert "try again" in strategy.lower()

    def test_success_method(self):
        """Test builder success method."""
        builder = MCPResponseBuilder()
        result = builder.success({"data": "value"}, "Operation completed")

        parsed = json.loads(get_text(result))
        assert parsed["status"] == "success"
        assert parsed["data"]["data"] == "value"
        assert parsed["message"] == "Operation completed"

    def test_error_method_with_auto_recovery(self):
        """Test builder error method with automatic recovery lookup."""
        builder = MCPResponseBuilder()
        result = builder.error("AUTH_REQUIRED", "No token provided")

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "AUTH_REQUIRED"
        assert "recovery_strategy" in parsed
        assert "JWT" in parsed["recovery_strategy"] or "token" in parsed["recovery_strategy"].lower()

    def test_error_method_with_override_recovery(self):
        """Test builder error method with overridden recovery strategy."""
        builder = MCPResponseBuilder()
        result = builder.error(
            "AUTH_REQUIRED",
            "No token",
            recovery_strategy="Custom recovery instruction",
        )

        parsed = json.loads(get_text(result))
        assert parsed["recovery_strategy"] == "Custom recovery instruction"

    def test_error_method_with_details(self):
        """Test builder error method with details."""
        builder = MCPResponseBuilder()
        result = builder.error(
            "NOT_FOUND",
            "Template not found",
            details={"template_id": "header"},
        )

        parsed = json.loads(get_text(result))
        assert parsed["details"]["template_id"] == "header"

    def test_from_exception_gofr_error(self):
        """Test converting GofrError to response."""
        builder = MCPResponseBuilder()
        exc = GofrError("CUSTOM_CODE", "Error message", {"key": "val"})
        result = builder.from_exception(exc)

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "CUSTOM_CODE"
        assert parsed["message"] == "Error message"
        assert parsed["details"]["key"] == "val"

    def test_from_exception_validation_error(self):
        """Test converting ValidationError subclass to response."""
        builder = MCPResponseBuilder()
        exc = ValidationError("VAL_ERR", "Invalid input", {"field": "name"})
        result = builder.from_exception(exc)

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "VAL_ERR"
        assert parsed["message"] == "Invalid input"

    def test_from_exception_override_code(self):
        """Test overriding error code when converting exception."""
        builder = MCPResponseBuilder()
        exc = GofrError("ORIGINAL", "Message")
        result = builder.from_exception(exc, error_code="OVERRIDDEN")

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "OVERRIDDEN"

    def test_from_exception_generic(self):
        """Test converting generic exception to response."""
        builder = MCPResponseBuilder()
        exc = ValueError("Something failed")
        result = builder.from_exception(exc)

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "INTERNAL_ERROR"
        assert "Something failed" in parsed["message"]

    def test_from_exception_merge_details(self):
        """Test merging additional details with exception details."""
        builder = MCPResponseBuilder()
        exc = GofrError("CODE", "Message", {"existing": "value"})
        result = builder.from_exception(exc, details={"additional": "info"})

        parsed = json.loads(get_text(result))
        assert parsed["details"]["existing"] == "value"
        assert parsed["details"]["additional"] == "info"

    def test_validation_error_method(self):
        """Test builder validation_error method."""
        builder = MCPResponseBuilder()
        errors = [{"type": "missing", "loc": ("field",), "msg": "required"}]
        result = builder.validation_error(errors, context="Test context")

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "VALIDATION_ERROR"
        assert parsed["details"]["context"] == "Test context"

    def test_method_chaining(self):
        """Test that set methods return self for chaining."""
        builder = MCPResponseBuilder()
        result = (
            builder
            .set_recovery_strategy("A", "Fix A")
            .set_recovery_strategies({"B": "Fix B", "C": "Fix C"})
        )

        assert result is builder
        assert builder.get_recovery_strategy("A") == "Fix A"
        assert builder.get_recovery_strategy("B") == "Fix B"
        assert builder.get_recovery_strategy("C") == "Fix C"


class TestIntegration:
    """Integration tests for MCP response utilities."""

    def test_typical_tool_handler_flow(self):
        """Test typical tool handler success/error flow."""
        builder = MCPResponseBuilder()
        builder.set_recovery_strategy("TEMPLATE_NOT_FOUND", "Check template exists")

        # Simulate success case
        success = builder.success(
            {"rendered": "<html>...</html>"},
            "Document rendered successfully",
        )
        success_parsed = json.loads(get_text(success))
        assert success_parsed["status"] == "success"

        # Simulate error case
        error = builder.error(
            "TEMPLATE_NOT_FOUND",
            "Template 'header' not found",
            details={"template_id": "header"},
        )
        error_parsed = json.loads(get_text(error))
        assert error_parsed["status"] == "error"
        assert error_parsed["recovery_strategy"] == "Check template exists"

    def test_exception_handling_flow(self):
        """Test exception handling in tool handler."""
        builder = MCPResponseBuilder()

        # Simulate catching exception
        try:
            raise ValidationError(
                "INVALID_FORMAT",
                "Date format is invalid",
                {"field": "date", "expected": "YYYY-MM-DD"},
            )
        except Exception as e:
            result = builder.from_exception(e)

        parsed = json.loads(get_text(result))
        assert parsed["error_code"] == "INVALID_FORMAT"
        assert parsed["details"]["field"] == "date"
