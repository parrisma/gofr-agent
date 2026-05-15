"""Tests for gofr_common.testing module.

This module tests the CodeQualityChecker class and pytest fixtures.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from gofr_common.testing import CheckResult, CodeQualityChecker

# ============================================================================
# Test CheckResult dataclass
# ============================================================================


class TestCheckResult:
    """Tests for the CheckResult dataclass."""

    def test_check_result_creation(self):
        """Test creating a CheckResult."""
        result = CheckResult(success=True, return_code=0, stdout="All checks passed", stderr="")
        assert result.success is True
        assert result.return_code == 0
        assert result.stdout == "All checks passed"
        assert result.stderr == ""
        assert result.error_message is None

    def test_check_result_with_error(self):
        """Test creating a CheckResult with an error."""
        result = CheckResult(
            success=False,
            return_code=1,
            stdout="",
            stderr="Error occurred",
            error_message="Linting failed",
        )
        assert result.success is False
        assert result.return_code == 1
        assert result.error_message == "Linting failed"

    def test_check_result_skipped(self):
        """Test creating a CheckResult for skipped check."""
        result = CheckResult(
            success=True, return_code=-1, stdout="", stderr="", error_message="Tool not found"
        )
        assert result.return_code == -1


# ============================================================================
# Test CodeQualityChecker initialization
# ============================================================================


class TestCodeQualityCheckerInit:
    """Tests for CodeQualityChecker initialization."""

    def test_init_with_path(self, tmp_path: Path):
        """Test initialization with a Path object."""
        checker = CodeQualityChecker(tmp_path)
        assert checker.project_root == tmp_path

    def test_init_with_string(self, tmp_path: Path):
        """Test initialization with a string path."""
        checker = CodeQualityChecker(str(tmp_path))
        assert checker.project_root == tmp_path

    def test_init_creates_absolute_path(self, tmp_path: Path):
        """Test that initialization creates absolute paths."""
        # Change to tmp_path and use relative path
        import os

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path.parent)
            checker = CodeQualityChecker(tmp_path.name)
            assert checker.project_root.is_absolute()
        finally:
            os.chdir(original_dir)


# ============================================================================
# Test tool finding
# ============================================================================


class TestFindTools:
    """Tests for finding ruff and pyright executables."""

    def test_find_ruff_exists(self, tmp_path: Path):
        """Test finding ruff when it exists."""
        checker = CodeQualityChecker(tmp_path)

        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/ruff"
            result = checker.find_ruff()
            assert result == Path("/usr/bin/ruff")

    def test_find_ruff_not_found(self, tmp_path: Path):
        """Test finding ruff when it doesn't exist."""
        checker = CodeQualityChecker(tmp_path)

        with patch("shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = checker.find_ruff()
                assert result is None

    def test_find_pyright_exists(self, tmp_path: Path):
        """Test finding pyright when it exists."""
        checker = CodeQualityChecker(tmp_path)

        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/pyright"
            result = checker.find_pyright()
            assert result == Path("/usr/bin/pyright")

    def test_find_pyright_not_found(self, tmp_path: Path):
        """Test finding pyright when it doesn't exist."""
        checker = CodeQualityChecker(tmp_path)

        with patch("shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = checker.find_pyright()
                assert result is None


# ============================================================================
# Test ruff checking
# ============================================================================


class TestRuffCheck:
    """Tests for ruff linting."""

    def test_ruff_check_success(self, tmp_path: Path):
        """Test ruff check with no errors."""
        checker = CodeQualityChecker(tmp_path)

        # Create a test directory
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        with patch.object(checker, "find_ruff", return_value=Path("/usr/bin/ruff")):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

                result = checker.run_ruff_check(["app"])

                assert result.success is True
                assert result.return_code == 0

    def test_ruff_check_with_errors(self, tmp_path: Path):
        """Test ruff check when errors are found."""
        checker = CodeQualityChecker(tmp_path)

        app_dir = tmp_path / "app"
        app_dir.mkdir()

        with patch.object(checker, "find_ruff", return_value=Path("/usr/bin/ruff")):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1, stdout="app/main.py:1:1: F401 'os' imported but unused", stderr=""
                )

                result = checker.run_ruff_check(["app"])

                assert result.success is False
                assert result.return_code == 1
                assert "F401" in result.stdout

    def test_ruff_check_not_found(self, tmp_path: Path):
        """Test ruff check when ruff is not installed."""
        checker = CodeQualityChecker(tmp_path)

        with patch.object(checker, "find_ruff", return_value=None):
            result = checker.run_ruff_check(["app"])

            assert result.success is True  # Not a failure, just skipped
            assert result.return_code == -1
            assert result.error_message is not None
            assert "not found" in result.error_message.lower()

    def test_ruff_check_no_dirs_exist(self, tmp_path: Path):
        """Test ruff check when no directories exist."""
        checker = CodeQualityChecker(tmp_path)

        with patch.object(checker, "find_ruff", return_value=Path("/usr/bin/ruff")):
            result = checker.run_ruff_check(["nonexistent"])

            assert result.success is True  # No dirs to check
            assert result.return_code == 0


# ============================================================================
# Test pyright checking
# ============================================================================


class TestPyrightCheck:
    """Tests for pyright type checking."""

    def test_pyright_check_success(self, tmp_path: Path):
        """Test pyright check with no errors."""
        checker = CodeQualityChecker(tmp_path)

        app_dir = tmp_path / "app"
        app_dir.mkdir()

        with patch.object(checker, "find_pyright", return_value=Path("/usr/bin/pyright")):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="0 errors, 0 warnings", stderr=""
                )

                result = checker.run_pyright_check(["app"])

                assert result.success is True
                assert result.return_code == 0

    def test_pyright_check_with_errors(self, tmp_path: Path):
        """Test pyright check when errors are found."""
        checker = CodeQualityChecker(tmp_path)

        app_dir = tmp_path / "app"
        app_dir.mkdir()

        with patch.object(checker, "find_pyright", return_value=Path("/usr/bin/pyright")):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="app/main.py:5:10 - error: Cannot find name 'foo'",
                    stderr="",
                )

                result = checker.run_pyright_check(["app"])

                assert result.success is False
                assert result.return_code == 1

    def test_pyright_check_not_found(self, tmp_path: Path):
        """Test pyright check when pyright is not installed."""
        checker = CodeQualityChecker(tmp_path)

        with patch.object(checker, "find_pyright", return_value=None):
            result = checker.run_pyright_check(["app"])

            assert result.success is True
            assert result.return_code == -1
            assert result.error_message is not None
            assert "not found" in result.error_message.lower()


# ============================================================================
# Test syntax checking
# ============================================================================


class TestSyntaxCheck:
    """Tests for Python syntax checking."""

    def test_syntax_check_valid(self, tmp_path: Path):
        """Test syntax check with valid Python files."""
        checker = CodeQualityChecker(tmp_path)

        # Create a valid Python file
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "main.py").write_text("def foo():\n    return 42\n")

        result = checker.check_syntax(["app"])

        assert result.success is True
        assert result.return_code == 0

    def test_syntax_check_invalid(self, tmp_path: Path):
        """Test syntax check with invalid Python files."""
        checker = CodeQualityChecker(tmp_path)

        # Create an invalid Python file
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "broken.py").write_text("def foo(\n    return 42\n")

        result = checker.check_syntax(["app"])

        assert result.success is False
        assert result.return_code == 1
        assert result.error_message is not None
        assert "broken.py" in result.error_message

    def test_syntax_check_empty_dir(self, tmp_path: Path):
        """Test syntax check with no Python files."""
        checker = CodeQualityChecker(tmp_path)

        # Create empty directory
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        result = checker.check_syntax(["app"])

        assert result.success is True

    def test_syntax_check_nonexistent_dir(self, tmp_path: Path):
        """Test syntax check with nonexistent directory."""
        checker = CodeQualityChecker(tmp_path)

        result = checker.check_syntax(["nonexistent"])

        assert result.success is True  # No files to check


# ============================================================================
# Test code statistics
# ============================================================================


class TestCodeStatistics:
    """Tests for code statistics generation."""

    def test_get_code_statistics(self, tmp_path: Path):
        """Test getting code statistics."""
        checker = CodeQualityChecker(tmp_path)

        # Create some Python files
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "main.py").write_text("def foo():\n    return 42\n\n\ndef bar():\n    pass\n")
        (app_dir / "utils.py").write_text("# Utils\nx = 1\ny = 2\n")

        file_count, line_count = checker.get_code_statistics(["app"])

        assert file_count == 2
        # Line count may vary slightly due to trailing newlines, just check reasonable range
        assert line_count >= 9 and line_count <= 11

    def test_get_code_statistics_nested(self, tmp_path: Path):
        """Test getting code statistics with nested directories."""
        checker = CodeQualityChecker(tmp_path)

        # Create nested structure
        app_dir = tmp_path / "app"
        sub_dir = app_dir / "sub"
        sub_dir.mkdir(parents=True)

        (app_dir / "main.py").write_text("x = 1\n")
        (sub_dir / "nested.py").write_text("y = 2\n")

        file_count, line_count = checker.get_code_statistics(["app"])

        assert file_count == 2
        assert line_count == 2

    def test_get_code_statistics_empty(self, tmp_path: Path):
        """Test getting code statistics for empty directory."""
        checker = CodeQualityChecker(tmp_path)

        file_count, line_count = checker.get_code_statistics(["nonexistent"])

        assert file_count == 0
        assert line_count == 0


# ============================================================================
# Test ruff configuration checking
# ============================================================================


class TestRuffConfigCheck:
    """Tests for checking ruff configuration."""

    def test_ruff_config_exists(self, tmp_path: Path):
        """Test checking when ruff config exists."""
        # Create pyproject.toml with ruff config
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F"]
"""
        )

        checker = CodeQualityChecker(tmp_path)
        assert checker.check_ruff_config() is True

    def test_ruff_config_missing(self, tmp_path: Path):
        """Test checking when ruff config is missing."""
        # Create pyproject.toml without ruff config
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[project]
name = "test"
version = "1.0.0"
"""
        )

        checker = CodeQualityChecker(tmp_path)
        assert checker.check_ruff_config() is False

    def test_ruff_config_no_pyproject(self, tmp_path: Path):
        """Test checking when pyproject.toml doesn't exist."""
        checker = CodeQualityChecker(tmp_path)
        assert checker.check_ruff_config() is False


# ============================================================================
# Test pytest fixtures module
# ============================================================================


class TestPytestFixtures:
    """Tests for pytest fixtures module."""

    def test_fixtures_importable(self):
        """Test that pytest fixtures module is importable."""
        from gofr_common.testing import pytest_fixtures

        assert hasattr(pytest_fixtures, "CodeQualityTestBase")
        assert hasattr(pytest_fixtures, "project_root")
        assert hasattr(pytest_fixtures, "code_quality_checker")

    def test_code_quality_test_base_class(self):
        """Test that CodeQualityTestBase has expected methods."""
        from gofr_common.testing.pytest_fixtures import CodeQualityTestBase

        # Check for expected test methods
        assert hasattr(CodeQualityTestBase, "test_no_linting_errors")
        assert hasattr(CodeQualityTestBase, "test_no_type_errors")
        assert hasattr(CodeQualityTestBase, "test_no_syntax_errors")
        assert hasattr(CodeQualityTestBase, "test_ruff_configuration_exists")
        assert hasattr(CodeQualityTestBase, "test_code_statistics")

        # Check for expected attributes
        assert hasattr(CodeQualityTestBase, "check_dirs")
