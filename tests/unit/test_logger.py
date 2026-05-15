"""Tests for app.logger re-exports."""

from app.logger import ConsoleLogger, DefaultLogger, Logger


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
