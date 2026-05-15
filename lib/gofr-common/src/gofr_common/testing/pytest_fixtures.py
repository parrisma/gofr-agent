"""Pytest fixtures and base test classes for GOFR code quality tests.

This module provides pytest fixtures and base test classes that can be
used in any GOFR project to enforce code quality standards.

Usage in project's conftest.py:
    from gofr_common.testing.pytest_fixtures import code_quality_fixtures

    # Import fixtures
    pytest_plugins = ["gofr_common.testing.pytest_fixtures"]

Or use the test classes directly:
    from gofr_common.testing.pytest_fixtures import CodeQualityTestBase

    class TestCodeQuality(CodeQualityTestBase):
        # Inherits all code quality tests
        pass
"""

from pathlib import Path
from typing import List

import pytest

from . import CodeQualityChecker


@pytest.fixture
def project_root(request) -> Path:
    """Get the project root directory.

    Determines the project root by walking up from the test file
    until we find a pyproject.toml.
    """
    # Start from the test file's directory
    start_path = Path(request.fspath).parent

    # Walk up until we find pyproject.toml
    current = start_path
    for _ in range(10):  # Safety limit
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    # Fallback: assume test is in test/ subdirectory
    return start_path.parent


@pytest.fixture
def code_quality_checker(project_root: Path) -> CodeQualityChecker:
    """Get a CodeQualityChecker instance for the project."""
    return CodeQualityChecker(project_root)


@pytest.fixture
def ruff_executable(code_quality_checker: CodeQualityChecker):
    """Get the path to the ruff executable or skip if not found."""
    ruff = code_quality_checker.find_ruff()
    if ruff is None:
        pytest.skip("ruff not found - install with: pip install ruff")
    return ruff


@pytest.fixture
def pyright_executable(code_quality_checker: CodeQualityChecker):
    """Get the path to the pyright executable or skip if not found."""
    pyright = code_quality_checker.find_pyright()
    if pyright is None:
        pytest.skip("pyright not found - install with: pip install pyright")
    return pyright


class CodeQualityTestBase:
    """Base class for code quality tests.

    Inherit from this class in your project's test file to get all
    standard code quality tests.

    Example:
        from gofr_common.testing.pytest_fixtures import CodeQualityTestBase

        class TestCodeQuality(CodeQualityTestBase):
            # Override check_dirs if needed
            check_dirs = ["app", "test", "scripts"]
    """

    # Directories to check - override in subclass if needed
    check_dirs: List[str] = ["app", "test", "scripts", "src"]

    @pytest.fixture
    def project_root(self) -> Path:
        """Get the project root directory.

        Override this fixture if your test file is not in a standard location.
        """
        # Default: assume test file is in test/code_quality/ or test/
        test_file = Path(__file__)

        # Walk up to find pyproject.toml
        current = test_file.parent
        for _ in range(5):
            if (current / "pyproject.toml").exists():
                return current
            current = current.parent

        # Fallback
        return test_file.parent.parent

    @pytest.fixture
    def checker(self, project_root: Path) -> CodeQualityChecker:
        """Get a CodeQualityChecker instance."""
        return CodeQualityChecker(project_root)

    def test_no_linting_errors(self, checker: CodeQualityChecker):
        """
        ZERO TOLERANCE: Enforce that there are no linting errors.

        This test runs ruff on the codebase and fails if any linting
        issues are found.
        """
        result = checker.run_ruff_check(self.check_dirs)

        if result.return_code == -1:
            pytest.skip(result.error_message or "ruff not found")

        if not result.success:
            pytest.fail(result.error_message or result.stdout)

    def test_no_type_errors(self, checker: CodeQualityChecker):
        """
        ZERO TOLERANCE: Enforce that there are no type errors.

        This test runs pyright on the codebase and fails if any type
        errors are found.
        """
        result = checker.run_pyright_check(self.check_dirs)

        if result.return_code == -1:
            pytest.skip(result.error_message or "pyright not found")

        if not result.success:
            pytest.fail(result.error_message or result.stdout)

    def test_no_syntax_errors(self, checker: CodeQualityChecker):
        """Verify that all Python files have valid syntax."""
        result = checker.check_syntax(self.check_dirs)

        if not result.success:
            pytest.fail(result.error_message or result.stdout)

    def test_ruff_configuration_exists(self, checker: CodeQualityChecker):
        """Verify that ruff configuration exists in pyproject.toml."""
        assert checker.check_ruff_config(), \
            "ruff configuration not found in pyproject.toml"

    def test_code_statistics(self, checker: CodeQualityChecker):
        """Generate code quality statistics (informational only)."""
        file_count, line_count = checker.get_code_statistics(self.check_dirs)

        print("\n\nCode Quality Statistics:")
        print(f"  Python files: {file_count}")
        print(f"  Total lines: {line_count:,}")
        print(f"  Average lines per file: {line_count // file_count if file_count else 0}")

        # This test always passes - it's just informational
        assert True
