#!/usr/bin/env python3
"""Code Quality Test Utilities for GOFR Projects.

This module provides reusable code quality test functions that enforce
zero-tolerance policies across all GOFR projects:
- No linting errors (ruff)
- No type errors (pyright)
- All issues must be fixed or explicitly marked with appropriate comments

ZERO TOLERANCE POLICY:
We maintain high code quality standards. Any linting or type error will fail
the build. If an error is a false positive, it must be explicitly suppressed
with a comment explaining why.

Usage in project tests:
    from gofr_common.testing import CodeQualityChecker

    checker = CodeQualityChecker(project_root=Path(__file__).parent.parent)
    checker.run_ruff_check(["app", "test"])
    checker.run_pyright_check(["app", "test"])

Or use the pytest base class (recommended):
    from gofr_common.testing.pytest_fixtures import CodeQualityTestBase

    class TestCodeQuality(CodeQualityTestBase):
        check_dirs = ["app", "test", "scripts"]
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

__all__ = [
    "CheckResult",
    "CodeQualityChecker",
]


@dataclass
class CheckResult:
    """Result of a code quality check."""

    success: bool
    stdout: str
    stderr: str
    return_code: int
    error_message: Optional[str] = None


class CodeQualityChecker:
    """Code quality checker for GOFR projects.

    Provides methods to run linting (ruff) and type checking (pyright)
    with consistent error messages and zero-tolerance policy enforcement.

    Example:
        checker = CodeQualityChecker(project_root=Path("/path/to/project"))

        # Run all checks
        result = checker.run_ruff_check(["app", "test"])
        if not result.success:
            print(result.error_message)

        result = checker.run_pyright_check(["app"])
        if not result.success:
            print(result.error_message)
    """

    def __init__(self, project_root: Path | str):
        """Initialize the code quality checker.

        Args:
            project_root: Path to the project root directory
        """
        self.project_root = Path(project_root).resolve()

    def find_ruff(self) -> Optional[Path]:
        """Find the ruff executable.

        Returns:
            Path to ruff executable, or None if not found.
        """
        # Check venv first
        venv_ruff = self.project_root / ".venv" / "bin" / "ruff"
        if venv_ruff.exists():
            return venv_ruff

        # Try shutil.which (system PATH)
        ruff_path = shutil.which("ruff")
        if ruff_path:
            return Path(ruff_path)

        return None

    def find_pyright(self) -> Optional[Path]:
        """Find the pyright executable.

        Returns:
            Path to pyright executable, or None if not found.
        """
        # Check venv first
        venv_pyright = self.project_root / ".venv" / "bin" / "pyright"
        if venv_pyright.exists():
            return venv_pyright

        # Try shutil.which (system PATH)
        pyright_path = shutil.which("pyright")
        if pyright_path:
            return Path(pyright_path)

        return None

    def run_ruff_check(self, check_dirs: List[str]) -> CheckResult:
        """Run ruff linting check.

        Args:
            check_dirs: List of directories to check (e.g., ["app", "test"])

        Returns:
            CheckResult with success status and any error messages.
            If ruff is not found, returns success=True with return_code=-1 (skip).
        """
        ruff = self.find_ruff()
        if ruff is None:
            return CheckResult(
                success=True,  # Not a failure, just skipped
                stdout="",
                stderr="",
                return_code=-1,
                error_message="ruff not found - install with: pip install ruff"
            )

        # Filter to directories that exist
        existing_dirs = [d for d in check_dirs if (self.project_root / d).exists()]
        if not existing_dirs:
            return CheckResult(
                success=True,
                stdout="No directories to check",
                stderr="",
                return_code=0
            )

        # ruff is a Path now, convert to string for command
        result = subprocess.run(
            [str(ruff), "check"] + existing_dirs + ["--output-format=concise", "--no-fix"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            error_message = self._format_ruff_error(result.stdout, str(ruff), existing_dirs)
            return CheckResult(
                success=False,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                error_message=error_message
            )

        return CheckResult(
            success=True,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode
        )

    def run_pyright_check(self, check_dirs: List[str]) -> CheckResult:
        """Run pyright type check.

        Args:
            check_dirs: List of directories to check (e.g., ["app", "test"])

        Returns:
            CheckResult with success status and any error messages.
            If pyright is not found, returns success=True with return_code=-1 (skip).
        """
        pyright = self.find_pyright()
        if pyright is None:
            return CheckResult(
                success=True,  # Not a failure, just skipped
                stdout="",
                stderr="",
                return_code=-1,
                error_message="pyright not found - install with: pip install pyright"
            )

        # Filter to directories that exist
        existing_dirs = [d for d in check_dirs if (self.project_root / d).exists()]
        if not existing_dirs:
            return CheckResult(
                success=True,
                stdout="No directories to check",
                stderr="",
                return_code=0
            )

        # pyright is a Path now, convert to string for command
        cmd = [str(pyright)] + existing_dirs
        result = subprocess.run(
            cmd,
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            error_message = self._format_pyright_error(result.stdout, result.stderr)
            return CheckResult(
                success=False,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                error_message=error_message
            )

        return CheckResult(
            success=True,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode
        )

    def check_syntax(self, check_dirs: List[str]) -> CheckResult:
        """Check all Python files for syntax errors.

        Args:
            check_dirs: List of directories to check

        Returns:
            CheckResult with success status and any error messages.
        """
        python_files = []
        for directory in check_dirs:
            dir_path = self.project_root / directory
            if dir_path.exists():
                python_files.extend(dir_path.rglob("*.py"))

        syntax_errors = []
        for py_file in python_files:
            try:
                compile(py_file.read_text(), str(py_file), "exec")
            except SyntaxError as e:
                syntax_errors.append(f"{py_file}: {e}")

        if syntax_errors:
            error_message = self._format_syntax_errors(syntax_errors)
            return CheckResult(
                success=False,
                stdout="\n".join(syntax_errors),
                stderr="",
                return_code=1,
                error_message=error_message
            )

        return CheckResult(
            success=True,
            stdout=f"Checked {len(python_files)} files",
            stderr="",
            return_code=0
        )

    def get_code_statistics(self, check_dirs: List[str]) -> Tuple[int, int]:
        """Get code statistics for the project.

        Args:
            check_dirs: List of directories to analyze

        Returns:
            Tuple of (file_count, line_count)
        """
        python_files = []
        for directory in check_dirs:
            dir_path = self.project_root / directory
            if dir_path.exists():
                python_files.extend(dir_path.rglob("*.py"))

        total_lines = 0
        for py_file in python_files:
            try:
                total_lines += len(py_file.read_text().splitlines())
            except Exception:
                pass

        return len(python_files), total_lines

    def check_ruff_config(self) -> bool:
        """Check if ruff configuration exists in pyproject.toml.

        Returns:
            True if configuration exists, False otherwise.
        """
        pyproject = self.project_root / "pyproject.toml"
        if not pyproject.exists():
            return False

        content = pyproject.read_text()
        return "[tool.ruff]" in content

    def _format_ruff_error(self, stdout: str, ruff: str, check_dirs: List[str]) -> str:
        """Format a ruff error message."""
        return "\n".join([
            "",
            "=" * 80,
            "ZERO TOLERANCE POLICY VIOLATION: LINTING ERRORS DETECTED",
            "=" * 80,
            "",
            "We maintain a zero-tolerance policy for linting errors.",
            "All code must pass linting checks before being committed.",
            "",
            "LINTING ERRORS FOUND:",
            "",
            stdout,
            "",
            "HOW TO FIX:",
            "",
            "1. Run automatic fixes:",
            f"   {ruff} check {' '.join(check_dirs)} --fix",
            "",
            "2. For false positives, add # noqa comment with explanation:",
            "   from module import foo  # noqa: F401 - imported for re-export",
            "",
            "3. Review and commit the changes",
            "",
            "COMMON ISSUES:",
            "",
            "- F401: Unused import - remove or add # noqa with reason",
            "- F841: Unused variable - remove or add # noqa with reason",
            "- E402: Module level import not at top - move import or add # noqa",
            "",
            "For more information: https://docs.astral.sh/ruff/rules/",
            "",
            "=" * 80,
        ])

    def _format_pyright_error(self, stdout: str, stderr: str) -> str:
        """Format a pyright error message."""
        return "\n".join([
            "",
            "=" * 80,
            "ZERO TOLERANCE POLICY VIOLATION: TYPE ERRORS DETECTED",
            "=" * 80,
            "",
            "We maintain a zero-tolerance policy for type errors.",
            "All code must pass type checking before being committed.",
            "These are the same errors that Pylance shows in VS Code.",
            "",
            "TYPE ERRORS FOUND:",
            "",
            stdout,
            "",
            stderr if stderr else "",
            "",
            "HOW TO FIX:",
            "",
            "1. Add or correct type annotations:",
            "   def my_func(x: int, y: str) -> bool:",
            "",
            "2. Use proper type hints for complex types:",
            "   from typing import Dict, List, Optional, Union",
            "   def process(data: Dict[str, List[int]]) -> Optional[str]:",
            "",
            "3. For dynamic types, use Any:",
            "   from typing import Any",
            "   def dynamic_func(x: Any) -> Any:",
            "",
            "4. Use type: ignore for unavoidable issues:",
            "   result = some_untyped_lib()  # type: ignore[attr-defined]",
            "",
            "For more information:",
            "https://microsoft.github.io/pyright/",
            "",
            "=" * 80,
        ])

    def _format_syntax_errors(self, errors: List[str]) -> str:
        """Format syntax error messages."""
        return "\n".join([
            "",
            "=" * 80,
            "SYNTAX ERRORS DETECTED",
            "=" * 80,
            "",
            "The following files have syntax errors:",
            "",
        ] + errors + [
            "",
            "=" * 80,
        ])
