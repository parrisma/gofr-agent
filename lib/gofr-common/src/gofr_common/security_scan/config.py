"""Configuration for Trivy-based security scanning."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_ALLOWED_SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


@dataclass
class SecurityScanConfig:
    """Configuration contract for container vulnerability scanning."""

    env_prefix: str = "GOFR"
    enabled: bool = True
    severities: List[str] | None = None
    fail_on_severity: str = "HIGH"
    timeout_seconds: int = 300
    ignore_unfixed: bool = False
    ignore_file: Optional[Path] = None
    report_path: Path = Path("artifacts/trivy-report.json")

    def __post_init__(self) -> None:
        self.env_prefix = self.env_prefix.upper().rstrip("_")
        if self.severities is None:
            self.severities = ["CRITICAL", "HIGH"]
        self.severities = [item.upper() for item in self.severities]

        if self.fail_on_severity.upper() not in _ALLOWED_SEVERITIES:
            raise ValueError(
                f"fail_on_severity must be one of {_ALLOWED_SEVERITIES}, got {self.fail_on_severity!r}"
            )
        self.fail_on_severity = self.fail_on_severity.upper()

        invalid = [item for item in self.severities if item not in _ALLOWED_SEVERITIES]
        if invalid:
            raise ValueError(f"Invalid severities: {invalid}. Allowed: {_ALLOWED_SEVERITIES}")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self.report_path = Path(self.report_path)
        if self.ignore_file is not None:
            self.ignore_file = Path(self.ignore_file)

    @classmethod
    def from_env(cls, env_prefix: str = "GOFR") -> "SecurityScanConfig":
        prefix = env_prefix.upper().rstrip("_")

        severities_raw = os.environ.get(f"{prefix}_TRIVY_SEVERITIES", "CRITICAL,HIGH")
        severities = [item.strip().upper() for item in severities_raw.split(",") if item.strip()]

        ignore_file_raw = os.environ.get(f"{prefix}_TRIVY_IGNORE_FILE")
        report_path_raw = os.environ.get(f"{prefix}_TRIVY_REPORT_PATH", "artifacts/trivy-report.json")

        return cls(
            env_prefix=prefix,
            enabled=_parse_bool(os.environ.get(f"{prefix}_TRIVY_ENABLED"), default=True),
            severities=severities,
            fail_on_severity=os.environ.get(f"{prefix}_TRIVY_FAIL_ON_SEVERITY", "HIGH"),
            timeout_seconds=_parse_positive_int(
                os.environ.get(f"{prefix}_TRIVY_TIMEOUT_SECONDS"),
                default=300,
                field_name=f"{prefix}_TRIVY_TIMEOUT_SECONDS",
            ),
            ignore_unfixed=_parse_bool(
                os.environ.get(f"{prefix}_TRIVY_IGNORE_UNFIXED"),
                default=False,
            ),
            ignore_file=Path(ignore_file_raw) if ignore_file_raw else None,
            report_path=Path(report_path_raw),
        )


def _parse_positive_int(raw: Optional[str], default: int, field_name: str) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0, got {value}")
    return value


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw!r}")


def fail_severities(fail_on_severity: str) -> List[str]:
    """Return severities that should trigger policy failure."""
    ordered = ["UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    threshold = fail_on_severity.upper()
    if threshold not in ordered:
        raise ValueError(f"Unknown fail severity threshold: {fail_on_severity}")
    idx = ordered.index(threshold)
    return ordered[idx:]
