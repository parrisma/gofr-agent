"""Tests for gofr_common.logger module.

Comprehensive tests for all logger implementations ensuring consistent
behavior across all GOFR projects.
"""

import io
import json
import logging
import os
import tempfile
from unittest import mock

import pytest

from gofr_common.logger import (
    ConsoleLogger,
    DefaultLogger,
    Logger,
    StructuredLogger,
    create_logger,
    get_logger,
)


class TestLoggerInterface:
    """Tests for the Logger abstract interface."""

    def test_logger_is_abstract(self):
        """Test that Logger cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Logger()  # type: ignore

    def test_logger_has_required_methods(self):
        """Test that Logger defines all required abstract methods."""
        assert hasattr(Logger, "debug")
        assert hasattr(Logger, "info")
        assert hasattr(Logger, "warning")
        assert hasattr(Logger, "error")
        assert hasattr(Logger, "critical")
        assert hasattr(Logger, "get_session_id")


class TestDefaultLogger:
    """Tests for the DefaultLogger implementation."""

    def test_default_logger_creates_session_id(self):
        """Test that DefaultLogger creates a unique session ID."""
        logger = DefaultLogger()
        session_id = logger.get_session_id()
        assert session_id is not None
        assert len(session_id) == 36  # UUID format

    def test_default_logger_different_instances_have_different_session_ids(self):
        """Test that different logger instances have different session IDs."""
        logger1 = DefaultLogger()
        logger2 = DefaultLogger()
        assert logger1.get_session_id() != logger2.get_session_id()

    def test_default_logger_writes_to_output(self):
        """Test that DefaultLogger writes to the specified output."""
        output = io.StringIO()
        logger = DefaultLogger(output=output)
        logger.info("Test message")

        output_str = output.getvalue()
        assert "INFO" in output_str
        assert "Test message" in output_str

    def test_default_logger_includes_session_id_in_output(self):
        """Test that output includes session ID."""
        output = io.StringIO()
        logger = DefaultLogger(output=output)
        logger.info("Test message")

        output_str = output.getvalue()
        assert "session:" in output_str
        assert logger.get_session_id()[:8] in output_str

    def test_default_logger_includes_timestamp_by_default(self):
        """Test that output includes timestamp by default."""
        output = io.StringIO()
        logger = DefaultLogger(output=output)
        logger.info("Test message")

        output_str = output.getvalue()
        # ISO format contains 'T' between date and time
        assert "T" in output_str

    def test_default_logger_can_disable_timestamp(self):
        """Test that timestamp can be disabled."""
        output = io.StringIO()
        logger = DefaultLogger(output=output, include_timestamp=False)
        logger.info("Test message")

        output_str = output.getvalue()
        # Without timestamp, should start with level
        assert output_str.startswith("[INFO]")

    def test_default_logger_all_levels(self):
        """Test that all log levels work."""
        output = io.StringIO()
        logger = DefaultLogger(output=output)

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

        output_str = output.getvalue()
        assert "DEBUG" in output_str
        assert "INFO" in output_str
        assert "WARNING" in output_str
        assert "ERROR" in output_str
        assert "CRITICAL" in output_str

    def test_default_logger_accepts_kwargs(self):
        """Test that logger accepts and formats keyword arguments."""
        output = io.StringIO()
        logger = DefaultLogger(output=output)
        logger.info("Test message", key="value", number=42)

        output_str = output.getvalue()
        assert "key=value" in output_str
        assert "number=42" in output_str

    def test_default_logger_includes_name(self):
        """Test that output includes logger name."""
        output = io.StringIO()
        logger = DefaultLogger(name="test-logger", output=output)
        logger.info("Test message")

        output_str = output.getvalue()
        assert "test-logger" in output_str


class TestConsoleLogger:
    """Tests for the ConsoleLogger implementation."""

    def test_console_logger_creates_session_id(self):
        """Test that ConsoleLogger creates a unique session ID."""
        logger = ConsoleLogger(name="test-console")
        session_id = logger.get_session_id()
        assert session_id is not None
        assert len(session_id) == 8  # Truncated UUID

    def test_console_logger_different_instances_have_different_session_ids(self):
        """Test that different logger instances have different session IDs."""
        logger1 = ConsoleLogger(name="test-1")
        logger2 = ConsoleLogger(name="test-2")
        assert logger1.get_session_id() != logger2.get_session_id()

    def test_console_logger_uses_python_logging(self):
        """Test that ConsoleLogger wraps Python's logging module."""
        logger = ConsoleLogger(name="test-python-logging")
        # The internal logger should be a Python logging.Logger
        assert hasattr(logger, "_logger")
        assert isinstance(logger._logger, logging.Logger)

    def test_console_logger_respects_level(self):
        """Test that ConsoleLogger respects the logging level."""
        logger = ConsoleLogger(name="test-level", level=logging.WARNING)
        assert logger._logger.level == logging.WARNING

    def test_console_logger_all_levels(self):
        """Test that all log levels are available."""
        logger = ConsoleLogger(name="test-all-levels")

        # These should not raise exceptions
        logger.debug("Debug")
        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")
        logger.critical("Critical")

    def test_console_logger_accepts_kwargs(self):
        """Test that logger accepts keyword arguments."""
        logger = ConsoleLogger(name="test-kwargs")
        # Should not raise exception
        logger.info("Test message", key="value", number=42)


class TestStructuredLogger:
    """Tests for the StructuredLogger implementation."""

    def test_structured_logger_creates_session_id(self):
        """Test that StructuredLogger creates a unique session ID."""
        logger = StructuredLogger(name="test-structured")
        session_id = logger.get_session_id()
        assert session_id is not None
        assert len(session_id) == 8  # Truncated UUID

    def test_structured_logger_text_format(self, capsys):
        """Test that StructuredLogger outputs text format by default."""
        logger = StructuredLogger(name="test-text", json_format=False)
        logger.info("Test message")

        captured = capsys.readouterr()
        assert "INFO" in captured.out
        assert "Test message" in captured.out
        assert "test-text" in captured.out

    def test_structured_logger_json_format(self, capsys):
        """Test that StructuredLogger can output JSON format."""
        logger = StructuredLogger(name="test-json", json_format=True)
        logger.info("Test message")

        captured = capsys.readouterr()
        # Should be valid JSON
        log_entry = json.loads(captured.out.strip())
        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Test message"
        assert log_entry["logger"] == "test-json"
        assert "session_id" in log_entry

    def test_structured_logger_json_includes_extras(self, capsys):
        """Test that JSON format includes extra kwargs."""
        logger = StructuredLogger(name="test-json-extras", json_format=True)
        logger.info("Test message", request_id="abc123", duration_ms=45)

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())
        assert log_entry["request_id"] == "abc123"
        assert log_entry["duration_ms"] == 45

    def test_structured_logger_text_includes_extras(self, capsys):
        """Test that text format includes extra kwargs."""
        logger = StructuredLogger(name="test-text-extras", json_format=False)
        logger.info("Test message", key="value")

        captured = capsys.readouterr()
        assert "key=value" in captured.out

    def test_structured_logger_file_output(self):
        """Test that StructuredLogger can write to a file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = StructuredLogger(name="test-file", log_file=log_file)
            logger.info("File test message")

            # Force flush
            for handler in logger._logger.handlers:
                handler.flush()

            with open(log_file, "r") as f:
                content = f.read()

            assert "File test message" in content
        finally:
            os.unlink(log_file)

    def test_structured_logger_all_levels(self, capsys):
        """Test that all log levels work with StructuredLogger."""
        logger = StructuredLogger(name="test-levels", level=logging.DEBUG)

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

        captured = capsys.readouterr()
        assert "DEBUG" in captured.out
        assert "INFO" in captured.out
        assert "WARNING" in captured.out
        assert "ERROR" in captured.out
        assert "CRITICAL" in captured.out

    def test_structured_logger_handles_reserved_kwargs(self, capsys):
        """Test that reserved kwargs are prefixed to avoid conflicts."""
        logger = StructuredLogger(name="test-reserved", json_format=True)
        # "name" is a reserved LogRecord attribute
        logger.info("Test", name="should be prefixed")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())
        # The reserved key should be prefixed with underscore
        assert "_name" in log_entry


class TestLoggerFactoryFunctions:
    """Tests for create_logger and get_logger factory functions."""

    def test_create_logger_returns_logger(self):
        """Test that create_logger returns a Logger instance."""
        logger = create_logger(name="test-factory")
        assert isinstance(logger, Logger)

    def test_create_logger_respects_level(self, capsys):
        """Test that create_logger respects the level parameter."""
        logger = create_logger(name="test-level-factory", level=logging.WARNING)
        logger.info("Should not appear")
        logger.warning("Should appear")

        captured = capsys.readouterr()
        assert "Should not appear" not in captured.out
        assert "Should appear" in captured.out

    def test_create_logger_respects_json_format(self, capsys):
        """Test that create_logger respects the json_format parameter."""
        logger = create_logger(name="test-json-factory", json_format=True)
        logger.info("JSON test")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())
        assert log_entry["message"] == "JSON test"

    def test_get_logger_reads_env_level(self, capsys):
        """Test that get_logger reads log level from environment."""
        with mock.patch.dict(os.environ, {"TEST_PROJECT_LOG_LEVEL": "WARNING"}):
            logger = get_logger("test-project")
            logger.info("Should not appear")
            logger.warning("Should appear")

        captured = capsys.readouterr()
        assert "Should not appear" not in captured.out
        assert "Should appear" in captured.out

    def test_get_logger_reads_env_json(self, capsys):
        """Test that get_logger reads JSON format from environment."""
        with mock.patch.dict(os.environ, {"TEST_JSON_ENV_LOG_JSON": "true"}):
            logger = get_logger("test-json-env")
            logger.info("JSON env test")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())
        assert log_entry["message"] == "JSON env test"

    def test_env_prefix_conversion(self):
        """Test that logger names are correctly converted to env prefixes."""
        # Test with gofr-dig style name
        with mock.patch.dict(os.environ, {"GOFR_DIG_LOG_LEVEL": "DEBUG"}):
            logger = get_logger("gofr-dig")
            # Access internal logger via getattr for testing
            internal_logger = getattr(logger, "_logger", None)
            assert internal_logger is not None
            assert internal_logger.level == logging.DEBUG

    def test_default_level_is_info(self, capsys):
        """Test that default log level is INFO."""
        logger = get_logger("test-default-level")
        logger.debug("Debug should not appear")
        logger.info("Info should appear")

        captured = capsys.readouterr()
        assert "Debug should not appear" not in captured.out
        assert "Info should appear" in captured.out


class TestLoggerConsistency:
    """Tests ensuring consistent behavior across all logger implementations."""

    @pytest.mark.parametrize("logger_class", [DefaultLogger, ConsoleLogger, StructuredLogger])
    def test_all_loggers_have_session_id(self, logger_class):
        """Test that all logger implementations provide session IDs."""
        if logger_class == DefaultLogger:
            logger = logger_class()
        else:
            logger = logger_class(name=f"test-{logger_class.__name__}")

        session_id = logger.get_session_id()
        assert session_id is not None
        assert isinstance(session_id, str)
        assert len(session_id) > 0

    @pytest.mark.parametrize("logger_class", [DefaultLogger, ConsoleLogger, StructuredLogger])
    def test_all_loggers_accept_kwargs(self, logger_class):
        """Test that all logger implementations accept keyword arguments."""
        if logger_class == DefaultLogger:
            logger = logger_class(output=io.StringIO())
        else:
            logger = logger_class(name=f"test-kwargs-{logger_class.__name__}")

        # Should not raise exceptions
        logger.info("Test", key="value", number=42, flag=True)

    @pytest.mark.parametrize("level_method", ["debug", "info", "warning", "error", "critical"])
    def test_all_level_methods_exist(self, level_method):
        """Test that all level methods exist on all implementations."""
        for logger_class in [DefaultLogger, ConsoleLogger, StructuredLogger]:
            if logger_class == DefaultLogger:
                logger = logger_class()
            else:
                logger = logger_class(name=f"test-method-{level_method}")

            assert hasattr(logger, level_method)
            assert callable(getattr(logger, level_method))
