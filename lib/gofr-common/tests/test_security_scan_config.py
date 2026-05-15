"""Tests for gofr_common.security_scan.config."""

from pathlib import Path

import pytest

from gofr_common.security_scan.config import SecurityScanConfig, fail_severities


class TestSecurityScanConfig:
    def test_defaults(self):
        config = SecurityScanConfig()
        assert config.enabled is True
        assert config.severities == ["CRITICAL", "HIGH"]
        assert config.fail_on_severity == "HIGH"
        assert config.timeout_seconds == 300
        assert config.ignore_unfixed is False
        assert config.report_path == Path("artifacts/trivy-report.json")

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOFR_DIG_TRIVY_ENABLED", "false")
        monkeypatch.setenv("GOFR_DIG_TRIVY_SEVERITIES", "critical,high,medium")
        monkeypatch.setenv("GOFR_DIG_TRIVY_FAIL_ON_SEVERITY", "critical")
        monkeypatch.setenv("GOFR_DIG_TRIVY_TIMEOUT_SECONDS", "120")
        monkeypatch.setenv("GOFR_DIG_TRIVY_IGNORE_UNFIXED", "true")
        monkeypatch.setenv("GOFR_DIG_TRIVY_IGNORE_FILE", ".trivyignore")
        monkeypatch.setenv("GOFR_DIG_TRIVY_REPORT_PATH", "tmp/report.json")

        config = SecurityScanConfig.from_env("GOFR_DIG")

        assert config.enabled is False
        assert config.severities == ["CRITICAL", "HIGH", "MEDIUM"]
        assert config.fail_on_severity == "CRITICAL"
        assert config.timeout_seconds == 120
        assert config.ignore_unfixed is True
        assert config.ignore_file == Path(".trivyignore")
        assert config.report_path == Path("tmp/report.json")

    def test_invalid_timeout_raises(self):
        with pytest.raises(ValueError, match="must be > 0"):
            SecurityScanConfig(timeout_seconds=0)

    def test_invalid_bool_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOFR_DIG_TRIVY_ENABLED", "maybe")
        with pytest.raises(ValueError, match="Invalid boolean"):
            SecurityScanConfig.from_env("GOFR_DIG")


class TestFailSeverities:
    def test_fail_severities_high(self):
        assert fail_severities("HIGH") == ["HIGH", "CRITICAL"]

    def test_fail_severities_critical(self):
        assert fail_severities("CRITICAL") == ["CRITICAL"]
