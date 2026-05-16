#!/usr/bin/env python3
"""Code Quality Gate for gofr-agent.

Enforces zero-tolerance policies for:
- Linting errors (ruff)
- Type errors (pyright)
- Security issues (bandit)

ZERO TOLERANCE POLICY:
All linting and security issues must be fixed or explicitly suppressed with
a comment explaining why (e.g., # noqa: F401 - imported for re-export).
"""

import subprocess
from pathlib import Path

import pytest

# Directories checked by all quality tools
CHECK_DIRS = ["app", "tests", "scripts"]
MIGRATED_LOGGING_FILES = [
    "app/main_mcp.py",
    "app/mcp_server/mcp_server.py",
    "app/agent/agent.py",
    "app/hub/auth.py",
    "app/hub/errors.py",
    "app/hub/store.py",
    "app/services/pool.py",
    "app/services/registry.py",
    "app/sessions/store.py",
]


class TestCodeQuality:
    """Enforces code quality standards as a build gate."""

    @pytest.fixture
    def project_root(self) -> Path:
        """Return the project root directory."""
        return Path(__file__).parent.parent.parent

    @pytest.fixture
    def ruff_executable(self, project_root: Path) -> str:
        """Resolve the ruff executable path."""
        venv_ruff = project_root / ".venv" / "bin" / "ruff"
        if venv_ruff.exists():
            return str(venv_ruff)
        result = subprocess.run(["which", "ruff"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        pytest.skip("ruff not found — install with: uv add --dev ruff")

    @pytest.fixture
    def pyright_executable(self, project_root: Path) -> str:
        """Resolve the pyright executable path."""
        venv_pyright = project_root / ".venv" / "bin" / "pyright"
        if venv_pyright.exists():
            return str(venv_pyright)
        result = subprocess.run(["which", "pyright"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        # Fall back to npx pyright
        npx_result = subprocess.run(
            ["npx", "--version"], capture_output=True, text=True, check=False
        )
        if npx_result.returncode == 0:
            return "npx pyright"
        pytest.skip("pyright not found — install with: uv add --dev pyright")

    @pytest.fixture
    def bandit_executable(self, project_root: Path) -> str:
        """Resolve the bandit executable path."""
        venv_bandit = project_root / ".venv" / "bin" / "bandit"
        if venv_bandit.exists():
            return str(venv_bandit)
        result = subprocess.run(["which", "bandit"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        pytest.skip("bandit not found — install with: uv add --dev bandit")

    # -------------------------------------------------------------------------
    # Linting gate
    # -------------------------------------------------------------------------

    def test_no_linting_errors(self, project_root: Path, ruff_executable: str) -> None:
        """
        ZERO TOLERANCE: No linting errors anywhere in the codebase.

        Runs ruff on app/, tests/, and scripts/. Any violation fails the build.

        Policy:
        - All errors MUST be fixed.
        - False positives MUST be suppressed with # noqa and an explanation.
          Example: from mod import Foo  # noqa: F401 - re-exported in __init__

        Auto-fix command:
            ruff check app tests scripts --fix
        """
        existing_dirs = [d for d in CHECK_DIRS if (project_root / d).exists()]
        if not existing_dirs:
            pytest.skip("No source directories found yet (pre-implementation)")

        result = subprocess.run(
            [ruff_executable, "check"] + existing_dirs + ["--output-format=concise", "--no-fix"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.fail(
                "\n".join(
                    [
                        "",
                        "=" * 70,
                        "ZERO TOLERANCE VIOLATION: LINTING ERRORS",
                        "=" * 70,
                        "",
                        result.stdout,
                        "",
                        "Fix automatically: ruff check app tests scripts --fix",
                        "Suppress false positives: # noqa: <CODE> - <reason>",
                        "=" * 70,
                    ]
                )
            )

    # -------------------------------------------------------------------------
    # Type-checking gate
    # -------------------------------------------------------------------------

    def test_no_type_errors(self, project_root: Path, pyright_executable: str) -> None:
        """
        ZERO TOLERANCE: No type errors in app/ (tests and scripts are lenient).

        Runs pyright on app/ only; pyproject.toml configures typeCheckingMode.
        All type errors must be fixed or annotated with # type: ignore[code].

        Policy:
        - Add proper type annotations.
        - Use Any for genuinely dynamic types.
        - Use # type: ignore[attr-defined] only as a last resort with a comment.
        """
        app_dir = project_root / "app"
        if not app_dir.exists():
            pytest.skip("app/ not found yet (pre-implementation)")

        cmd = pyright_executable.split() + ["app"]
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.fail(
                "\n".join(
                    [
                        "",
                        "=" * 70,
                        "ZERO TOLERANCE VIOLATION: TYPE ERRORS",
                        "=" * 70,
                        "",
                        result.stdout,
                        result.stderr if result.stderr else "",
                        "",
                        "Fix: add/correct type annotations, or use # type: ignore[code]",
                        "Docs: https://microsoft.github.io/pyright/",
                        "=" * 70,
                    ]
                )
            )

    # -------------------------------------------------------------------------
    # Security gate
    # -------------------------------------------------------------------------

    def test_no_security_issues(self, project_root: Path, bandit_executable: str) -> None:
        """
        ZERO TOLERANCE: No medium-or-higher severity security issues in app/.

        Runs bandit with:
        - Severity: medium and above (-ll)
        - Confidence: medium and above (-ii)
        - Skips: B104 (binding to all interfaces — acceptable for a server)

        Policy:
        - All issues must be fixed.
        - If a finding is a known false positive, add # nosec B<CODE> with a comment.
          Example: host = "0.0.0.0"  # nosec B104 - intentional server bind address

        OWASP coverage enforced:
        - A01 Broken Access Control — caught via B105/B106/B107 (hardcoded secrets)
        - A02 Cryptographic Failures — caught via B323/B501/B502 (weak crypto)
        - A03 Injection — caught via B601/B602/B605 (shell injection)
        - A08 Software Integrity — caught via B506/B324 (insecure deserialisation)
        """
        app_dir = project_root / "app"
        if not app_dir.exists():
            pytest.skip("app/ not found yet (pre-implementation)")

        result = subprocess.run(
            [
                bandit_executable,
                "-r",
                "app",
                "-ll",   # medium+ severity
                "-ii",   # medium+ confidence
                "--skip", "B104",  # binding 0.0.0.0 is intentional for a server
                "-f", "txt",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.fail(
                "\n".join(
                    [
                        "",
                        "=" * 70,
                        "ZERO TOLERANCE VIOLATION: SECURITY ISSUES (bandit)",
                        "=" * 70,
                        "",
                        result.stdout,
                        result.stderr if result.stderr else "",
                        "",
                        "Fix: resolve the security issue, or add",
                        "  # nosec B<CODE> - <explanation>",
                        "Docs: https://bandit.readthedocs.io/",
                        "=" * 70,
                    ]
                )
            )

    # -------------------------------------------------------------------------
    # Import hygiene smoke test
    # -------------------------------------------------------------------------

    def test_app_package_importable(self, project_root: Path) -> None:
        """
        Verify that the app package can be imported without errors.

        This catches missing __init__.py files, circular imports, and syntax
        errors that static analysis might miss.
        """
        app_dir = project_root / "app"
        if not (app_dir / "__init__.py").exists():
            pytest.skip("app/__init__.py not found yet (pre-implementation)")

        result = subprocess.run(
            ["python", "-c", "import app"],
            cwd=project_root,
            capture_output=True,
            text=True,
            env=_test_env(project_root),
        )

        if result.returncode != 0:
            pytest.fail(
                "\n".join(
                    [
                        "",
                        "IMPORT ERROR: app package cannot be imported",
                        "",
                        result.stderr,
                        "",
                        "Fix circular imports or missing __init__.py files.",
                    ]
                )
            )

    def test_migrated_modules_do_not_use_stdlib_logging(self, project_root: Path) -> None:
        """Prevent reasoning-path modules from slipping back to stdlib logging."""
        violations: list[str] = []

        for relative_path in MIGRATED_LOGGING_FILES:
            file_path = project_root / relative_path
            if not file_path.exists():
                continue
            content = file_path.read_text(encoding="utf-8")
            if "import logging" in content:
                violations.append(f"{relative_path}: import logging")
            if "logging.getLogger" in content:
                violations.append(f"{relative_path}: logging.getLogger")
            if "logging.LoggerAdapter" in content:
                violations.append(f"{relative_path}: logging.LoggerAdapter")

        if violations:
            pytest.fail(
                "\n".join(
                    ["Stdlib logging is forbidden in migrated modules:"] + violations
                )
            )


# =============================================================================
# Helpers
# =============================================================================

def _test_env(project_root: Path) -> dict:
    """Build a minimal environment for subprocess import checks."""
    import os

    env = os.environ.copy()
    lib_path = project_root / "lib" / "gofr-common" / "src"
    existing = env.get("PYTHONPATH", "")
    parts = [str(project_root), str(lib_path)] + ([existing] if existing else [])
    env["PYTHONPATH"] = ":".join(parts)
    # Prevent import-time config errors
    env.setdefault("GOFR_AGENT_JWT_SECRET", "test-secret")
    env.setdefault("GOFR_AGENT_ENV", "TEST")
    return env
