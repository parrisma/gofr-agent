"""Tests for runner and service orchestration."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from gofr_common.security_scan import SecurityScanConfig
from gofr_common.security_scan.runner import TrivyExecutionError, TrivyRunner
from gofr_common.security_scan.service import SecurityScanService


def test_runner_builds_and_executes_command(monkeypatch: pytest.MonkeyPatch):
    logger = Mock()
    runner = TrivyRunner(logger=logger)
    config = SecurityScanConfig(
        severities=["CRITICAL", "HIGH"],
        timeout_seconds=60,
        ignore_unfixed=True,
    )

    captured = {}

    def fake_run(cmd, check, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=json.dumps({"Results": []}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    payload = runner.run_image_scan("alpine:latest", config)
    assert payload == {"Results": []}
    assert captured["timeout"] == 60
    assert "--ignore-unfixed" in captured["cmd"]
    assert captured["cmd"][-1] == "alpine:latest"


def test_runner_raises_when_trivy_missing(monkeypatch: pytest.MonkeyPatch):
    logger = Mock()
    runner = TrivyRunner(logger=logger)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("trivy")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(TrivyExecutionError, match="not found"):
        runner.run_image_scan("alpine:latest", SecurityScanConfig())


def test_service_generates_report_and_writes_file(tmp_path: Path):
    runner = Mock()
    runner.run_image_scan.return_value = {
        "Metadata": {"Version": "0.60.0"},
        "Results": [
            {
                "Target": "alpine:latest",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-5",
                        "PkgName": "busybox",
                        "InstalledVersion": "1.0",
                        "FixedVersion": "1.1",
                        "Severity": "LOW",
                    }
                ],
            }
        ],
    }

    config = SecurityScanConfig(
        report_path=tmp_path / "scan-report.json",
        fail_on_severity="HIGH",
        ignore_unfixed=False,
    )
    service = SecurityScanService(config=config, runner=runner, logger=Mock())

    report = service.scan_image("alpine:latest")
    assert report.policy_decision == "pass"
    assert report.counts_by_severity["LOW"] == 1

    output_path = service.write_report(report)
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["target_image"] == "alpine:latest"
