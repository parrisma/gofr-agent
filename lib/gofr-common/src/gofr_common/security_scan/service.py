"""High-level security scan service orchestration."""

from __future__ import annotations

import json
from pathlib import Path

from gofr_common.logger import Logger, create_logger

from .config import SecurityScanConfig
from .models import NormalizedScanReport
from .normalize import normalize_trivy_json
from .policy import evaluate_policy
from .runner import TrivyExecutionError, TrivyRunner, create_runner


class SecurityScanService:
    """Runs Trivy scans and returns normalized/policy-evaluated reports."""

    def __init__(self, config: SecurityScanConfig, runner: TrivyRunner | None = None, logger: Logger | None = None):
        self.config = config
        self.logger = logger or create_logger("gofr-security-scan")
        self.runner = runner or create_runner(self.logger)

    def scan_image(self, image_ref: str) -> NormalizedScanReport:
        """Execute image scan and evaluate policy."""
        if not self.config.enabled:
            return NormalizedScanReport.create(
                target_image=image_ref,
                findings=[],
                counts_by_severity={"UNKNOWN": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0},
                policy_decision="pass",
                fail_reasons=[],
                metadata={"scan_enabled": False},
            )

        raw = self.runner.run_image_scan(image_ref=image_ref, config=self.config)
        findings, counts, trivy_version = normalize_trivy_json(raw, target_image=image_ref)

        decision = evaluate_policy(
            findings=findings,
            fail_on_severity=self.config.fail_on_severity,
            ignore_unfixed=self.config.ignore_unfixed,
        )

        report = NormalizedScanReport.create(
            target_image=image_ref,
            findings=findings,
            counts_by_severity=counts,
            policy_decision="pass" if decision.passed else "fail",
            fail_reasons=decision.reasons,
            trivy_version=trivy_version,
            metadata={
                "scan_enabled": True,
                "severity_filter": self.config.severities,
                "fail_on_severity": self.config.fail_on_severity,
                "ignore_unfixed": self.config.ignore_unfixed,
            },
        )

        self.logger.info(
            "Security scan completed",
            event="security_scan_completed",
            image_ref=image_ref,
            policy_decision=report.policy_decision,
            total_findings=len(findings),
            high_count=counts.get("HIGH", 0),
            critical_count=counts.get("CRITICAL", 0),
        )
        return report

    def write_report(self, report: NormalizedScanReport, path: Path | None = None) -> Path:
        """Persist normalized report to disk and return final path."""
        report_path = Path(path or self.config.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        self.logger.info(
            "Security scan report written",
            event="security_scan_report_written",
            report_path=str(report_path),
        )
        return report_path


__all__ = ["SecurityScanService", "SecurityScanConfig", "TrivyExecutionError"]
