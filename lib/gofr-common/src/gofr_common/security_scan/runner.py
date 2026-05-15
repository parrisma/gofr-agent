"""Trivy command execution wrapper with bounded retries and timeout controls."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List

from gofr_common.logger import Logger, create_logger

from .config import SecurityScanConfig


class TrivyExecutionError(RuntimeError):
    """Raised when Trivy cannot be executed or returns invalid output."""


@dataclass
class TrivyRunner:
    """Encapsulates Trivy process execution."""

    logger: Logger
    max_attempts: int = 2

    def run_image_scan(self, image_ref: str, config: SecurityScanConfig) -> Dict[str, Any]:
        """Run Trivy image scan and return parsed JSON payload."""
        if not image_ref or not image_ref.strip():
            raise ValueError("image_ref is required")

        cmd = self._build_command(image_ref=image_ref.strip(), config=config)

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self.logger.info(
                    "Running Trivy image scan",
                    event="security_scan_trivy_exec",
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    image_ref=image_ref,
                    timeout_seconds=config.timeout_seconds,
                )

                completed = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds,
                )

                if completed.returncode != 0:
                    stderr = completed.stderr.strip()
                    raise TrivyExecutionError(
                        f"Trivy exited with code {completed.returncode}. stderr={stderr}"
                    )

                try:
                    return json.loads(completed.stdout)
                except json.JSONDecodeError as exc:
                    raise TrivyExecutionError("Trivy returned malformed JSON output") from exc

            except FileNotFoundError as exc:
                raise TrivyExecutionError(
                    "Trivy executable not found on PATH. Install Trivy in the execution environment."
                ) from exc
            except subprocess.TimeoutExpired:
                last_error = TrivyExecutionError(
                    f"Trivy scan timed out after {config.timeout_seconds}s"
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc

            if attempt < self.max_attempts:
                self.logger.warning(
                    "Trivy scan attempt failed; retrying",
                    event="security_scan_trivy_retry",
                    attempt=attempt,
                    image_ref=image_ref,
                    error_type=type(last_error).__name__ if last_error else "UnknownError",
                )

        if isinstance(last_error, TrivyExecutionError):
            raise last_error
        if last_error is not None:
            raise TrivyExecutionError(str(last_error)) from last_error
        raise TrivyExecutionError("Trivy scan failed for unknown reason")

    def _build_command(self, image_ref: str, config: SecurityScanConfig) -> List[str]:
        cmd = [
            "trivy",
            "image",
            "--format",
            "json",
            "--quiet",
            "--scanners",
            "vuln",
            "--timeout",
            f"{config.timeout_seconds}s",
            "--severity",
            ",".join(config.severities or ["CRITICAL", "HIGH"]),
        ]

        if config.ignore_unfixed:
            cmd.append("--ignore-unfixed")

        if config.ignore_file:
            cmd.extend(["--ignorefile", str(config.ignore_file)])

        cmd.append(image_ref)
        return cmd


def create_runner(logger: Logger | None = None) -> TrivyRunner:
    """Create a TrivyRunner with default logger when not provided."""
    return TrivyRunner(logger=logger or create_logger("gofr-security-scan"))
