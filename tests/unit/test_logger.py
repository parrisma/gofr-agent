"""Tests for app.logger re-exports."""

from app.logger import ConsoleLogger, DefaultLogger, Logger, StructuredLogger, get_logger


class TestLoggerImports:
    def test_logger_importable(self) -> None:
        assert Logger is not None

    def test_default_logger_importable(self) -> None:
        assert DefaultLogger is not None

    def test_console_logger_importable(self) -> None:
        assert ConsoleLogger is not None

    def test_console_logger_instantiable(self) -> None:
        logger = ConsoleLogger(name="test")
        assert logger is not None

    def test_default_logger_instantiable(self) -> None:
        logger = DefaultLogger()
        assert logger is not None

    def test_structured_logger_importable(self) -> None:
        assert StructuredLogger is not None

    def test_get_logger_returns_structured_logger(self) -> None:
        logger = get_logger("gofr-agent.test")
        assert isinstance(logger, StructuredLogger)
