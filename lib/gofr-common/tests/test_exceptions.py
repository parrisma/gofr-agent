"""Tests for common exception hierarchy.

These tests verify:
1. Exception structure (code, message, details)
2. Inheritance hierarchy
3. String representation
4. Details handling
5. Dictionary conversion for JSON serialization
"""

import pytest

from gofr_common.exceptions import (
    ConfigurationError,
    GofrError,
    RegistryError,
    ResourceNotFoundError,
    SecurityError,
    ValidationError,
)


class TestGofrError:
    """Tests for base GofrError class."""

    def test_basic_construction(self):
        """Test basic exception construction."""
        error = GofrError("TEST_CODE", "Test message")

        assert error.code == "TEST_CODE"
        assert error.message == "Test message"
        assert error.details == {}

    def test_construction_with_details(self):
        """Test exception with details dict."""
        details = {"key1": "value1", "key2": 42}
        error = GofrError("TEST_CODE", "Test message", details=details)

        assert error.details == details
        assert error.details["key1"] == "value1"
        assert error.details["key2"] == 42

    def test_construction_with_none_details(self):
        """Test that None details becomes empty dict."""
        error = GofrError("TEST_CODE", "Test message", details=None)
        assert error.details == {}

    def test_str_without_details(self):
        """Test string representation without details."""
        error = GofrError("TEST_CODE", "Test message")

        assert str(error) == "TEST_CODE: Test message"

    def test_str_with_details(self):
        """Test string representation with details."""
        error = GofrError("TEST_CODE", "Test message", details={"foo": "bar"})

        result = str(error)
        assert "TEST_CODE" in result
        assert "Test message" in result
        assert "foo" in result
        assert "bar" in result

    def test_is_exception(self):
        """Test that GofrError is an Exception."""
        error = GofrError("TEST", "test")
        assert isinstance(error, Exception)

    def test_can_be_raised(self):
        """Test that exception can be raised and caught."""
        with pytest.raises(GofrError) as exc_info:
            raise GofrError("RAISED", "This was raised")

        assert exc_info.value.code == "RAISED"
        assert exc_info.value.message == "This was raised"

    def test_args_contains_message(self):
        """Test that Exception.args contains the message."""
        error = GofrError("CODE", "The error message")
        assert "The error message" in error.args

    def test_to_dict(self):
        """Test conversion to dictionary."""
        error = GofrError("TEST_CODE", "Test message", details={"key": "value"})
        result = error.to_dict()

        assert result == {
            "code": "TEST_CODE",
            "message": "Test message",
            "details": {"key": "value"},
        }

    def test_to_dict_empty_details(self):
        """Test conversion to dictionary with empty details."""
        error = GofrError("TEST_CODE", "Test message")
        result = error.to_dict()

        assert result == {
            "code": "TEST_CODE",
            "message": "Test message",
            "details": {},
        }


class TestValidationError:
    """Tests for ValidationError class."""

    def test_inherits_from_gofr_error(self):
        """Test ValidationError inherits from GofrError."""
        error = ValidationError("CODE", "message")
        assert isinstance(error, GofrError)

    def test_inherits_from_exception(self):
        """Test ValidationError is an Exception."""
        error = ValidationError("CODE", "message")
        assert isinstance(error, Exception)

    def test_can_be_caught_as_base(self):
        """Test ValidationError can be caught as GofrError."""
        with pytest.raises(GofrError):
            raise ValidationError("VAL", "validation failed")

    def test_has_all_attributes(self):
        """Test ValidationError has code, message, details."""
        error = ValidationError("INVALID_INPUT", "Input is invalid", {"field": "url"})

        assert error.code == "INVALID_INPUT"
        assert error.message == "Input is invalid"
        assert error.details["field"] == "url"

    def test_to_dict(self):
        """Test ValidationError to_dict works."""
        error = ValidationError("VAL_ERR", "Invalid", {"field": "name"})
        result = error.to_dict()

        assert result["code"] == "VAL_ERR"
        assert result["message"] == "Invalid"
        assert result["details"]["field"] == "name"


class TestResourceNotFoundError:
    """Tests for ResourceNotFoundError class."""

    def test_inherits_from_gofr_error(self):
        """Test ResourceNotFoundError inherits from GofrError."""
        error = ResourceNotFoundError("NOT_FOUND", "Resource not found")
        assert isinstance(error, GofrError)

    def test_inherits_from_exception(self):
        """Test ResourceNotFoundError is an Exception."""
        error = ResourceNotFoundError("NOT_FOUND", "Resource not found")
        assert isinstance(error, Exception)

    def test_can_be_caught_as_base(self):
        """Test ResourceNotFoundError can be caught as GofrError."""
        with pytest.raises(GofrError):
            raise ResourceNotFoundError("NOT_FOUND", "Resource not found")

    def test_resource_not_found_usage(self):
        """Test typical ResourceNotFoundError usage."""
        error = ResourceNotFoundError(
            "TEMPLATE_NOT_FOUND",
            "Template 'header' not found",
            {"template_id": "header", "groups": ["group1", "group2"]},
        )

        assert error.code == "TEMPLATE_NOT_FOUND"
        assert "header" in error.message
        assert error.details["template_id"] == "header"
        assert "group1" in error.details["groups"]


class TestSecurityError:
    """Tests for SecurityError class."""

    def test_inherits_from_gofr_error(self):
        """Test SecurityError inherits from GofrError."""
        error = SecurityError("ACCESS_DENIED", "Access denied")
        assert isinstance(error, GofrError)

    def test_inherits_from_exception(self):
        """Test SecurityError is an Exception."""
        error = SecurityError("ACCESS_DENIED", "Access denied")
        assert isinstance(error, Exception)

    def test_can_be_caught_as_base(self):
        """Test SecurityError can be caught as GofrError."""
        with pytest.raises(GofrError):
            raise SecurityError("GROUP_MISMATCH", "Group mismatch")

    def test_security_error_usage(self):
        """Test typical SecurityError usage."""
        error = SecurityError(
            "GROUP_MISMATCH",
            "Access denied: group mismatch",
            {"required_group": "admin", "user_group": "user"},
        )

        assert error.code == "GROUP_MISMATCH"
        assert error.details["required_group"] == "admin"


class TestConfigurationError:
    """Tests for ConfigurationError class."""

    def test_inherits_from_gofr_error(self):
        """Test ConfigurationError inherits from GofrError."""
        error = ConfigurationError("CONFIG_INVALID", "Invalid configuration")
        assert isinstance(error, GofrError)

    def test_inherits_from_exception(self):
        """Test ConfigurationError is an Exception."""
        error = ConfigurationError("CONFIG_INVALID", "Invalid configuration")
        assert isinstance(error, Exception)

    def test_can_be_caught_as_base(self):
        """Test ConfigurationError can be caught as GofrError."""
        with pytest.raises(GofrError):
            raise ConfigurationError("MISSING_SETTING", "Required setting missing")

    def test_configuration_error_usage(self):
        """Test typical ConfigurationError usage."""
        error = ConfigurationError(
            "MISSING_ENV_VAR",
            "Required environment variable not set",
            {"var_name": "DATABASE_URL", "required": True},
        )

        assert error.code == "MISSING_ENV_VAR"
        assert error.details["var_name"] == "DATABASE_URL"


class TestRegistryError:
    """Tests for RegistryError class."""

    def test_inherits_from_gofr_error(self):
        """Test RegistryError inherits from GofrError."""
        error = RegistryError("Registry operation failed")
        assert isinstance(error, GofrError)

    def test_inherits_from_exception(self):
        """Test RegistryError is an Exception."""
        error = RegistryError("Registry operation failed")
        assert isinstance(error, Exception)

    def test_can_be_caught_as_base(self):
        """Test RegistryError can be caught as GofrError."""
        with pytest.raises(GofrError):
            raise RegistryError("Registry error")

    def test_backward_compatible_construction(self):
        """Test RegistryError with message-only construction."""
        error = RegistryError("Something went wrong")

        assert error.code == "REGISTRY_ERROR"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_construction_with_custom_code(self):
        """Test RegistryError with custom code."""
        error = RegistryError("Custom error", code="CUSTOM_REGISTRY")

        assert error.code == "CUSTOM_REGISTRY"
        assert error.message == "Custom error"

    def test_construction_with_details(self):
        """Test RegistryError with details."""
        error = RegistryError("Error", code="REG_ERR", details={"item": "template"})

        assert error.details["item"] == "template"

    def test_str_representation(self):
        """Test RegistryError string representation."""
        error = RegistryError("Failed to load")
        assert str(error) == "REGISTRY_ERROR: Failed to load"


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_all_inherit_from_gofr_error(self):
        """Test all exception classes inherit from GofrError."""
        exceptions = [
            ValidationError("CODE", "msg"),
            ResourceNotFoundError("CODE", "msg"),
            SecurityError("CODE", "msg"),
            ConfigurationError("CODE", "msg"),
            RegistryError("msg"),
        ]

        for exc in exceptions:
            assert isinstance(exc, GofrError)

    def test_all_inherit_from_exception(self):
        """Test all exception classes inherit from Exception."""
        exceptions = [
            GofrError("CODE", "msg"),
            ValidationError("CODE", "msg"),
            ResourceNotFoundError("CODE", "msg"),
            SecurityError("CODE", "msg"),
            ConfigurationError("CODE", "msg"),
            RegistryError("msg"),
        ]

        for exc in exceptions:
            assert isinstance(exc, Exception)

    def test_exceptions_can_be_differentiated(self):
        """Test that different exception types can be caught separately."""
        errors = []

        try:
            raise ValidationError("VAL", "validation")
        except ValidationError as e:
            errors.append(("validation", e))

        try:
            raise ResourceNotFoundError("NOT_FOUND", "not found")
        except ResourceNotFoundError as e:
            errors.append(("not_found", e))

        try:
            raise SecurityError("SEC", "security")
        except SecurityError as e:
            errors.append(("security", e))

        assert len(errors) == 3
        assert errors[0][0] == "validation"
        assert errors[1][0] == "not_found"
        assert errors[2][0] == "security"

    def test_base_catch_all(self):
        """Test that GofrError catches all subclasses."""
        caught = []

        for exc_class in [ValidationError, ResourceNotFoundError, SecurityError, ConfigurationError]:
            try:
                raise exc_class("CODE", "message")
            except GofrError as e:
                caught.append(type(e).__name__)

        assert len(caught) == 4
        assert "ValidationError" in caught
        assert "ResourceNotFoundError" in caught
        assert "SecurityError" in caught
        assert "ConfigurationError" in caught


class TestAliasCompatibility:
    """Tests for creating project-specific aliases."""

    def test_alias_creation(self):
        """Test that aliases can be created for backward compatibility."""
        # Simulate what a project would do for backward compatibility
        GofrNpError = GofrError

        # Errors created with aliases work correctly
        error = GofrNpError("CODE", "message")
        assert isinstance(error, GofrError)
        assert error.code == "CODE"

    def test_subclass_with_alias_base(self):
        """Test that subclasses can use aliased base."""
        # Projects can create subclasses using the alias
        GofrNpError = GofrError

        class MathError(GofrNpError):
            """Math-specific error."""
            pass

        error = MathError("MATH_ERR", "Math error")
        assert isinstance(error, GofrError)
        assert error.code == "MATH_ERR"
