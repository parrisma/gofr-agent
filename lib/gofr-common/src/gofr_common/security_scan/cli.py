"""CLI entrypoint for Trivy-based security scanning."""

from __future__ import annotations

import argparse
from pathlib import Path

from gofr_common.logger import create_logger

from .config import SecurityScanConfig
from .runner import TrivyExecutionError
from .service import SecurityScanService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Trivy container vulnerability scan")
    parser.add_argument("--image", required=True, help="Container image reference (tag or digest)")
    parser.add_argument("--env-prefix", default="GOFR", help="Environment variable prefix")
    parser.add_argument("--report-path", default=None, help="Override output report path")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logger = create_logger("gofr-security-scan")
    config = SecurityScanConfig.from_env(env_prefix=args.env_prefix)
    if args.report_path:
        config.report_path = Path(args.report_path)

    service = SecurityScanService(config=config, logger=logger)

    try:
        report = service.scan_image(args.image)
        service.write_report(report)
        if report.policy_decision == "pass":
            return 0
        return 2
    except (TrivyExecutionError, ValueError) as exc:
        logger.error(
            "Security scan execution failed",
            event="security_scan_execution_failed",
            error_type=type(exc).__name__,
            cause=str(exc),
            remediation="verify_trivy_installation_image_reference_and_environment_configuration",
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
