"""Tests for security scan CLI contract."""

from unittest.mock import Mock

import pytest

from gofr_common.security_scan import cli


def test_cli_returns_policy_fail_exit_code(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["gofr-security-scan", "--image", "alpine:latest"])

    fake_service = Mock()
    fake_service.scan_image.return_value = Mock(policy_decision="fail")
    fake_service.write_report.return_value = None

    monkeypatch.setattr(cli, "SecurityScanService", lambda config, logger: fake_service)

    exit_code = cli.main()
    assert exit_code == 2


def test_cli_returns_execution_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["gofr-security-scan", "--image", "alpine:latest"])

    fake_service = Mock()
    fake_service.scan_image.side_effect = ValueError("bad input")

    monkeypatch.setattr(cli, "SecurityScanService", lambda config, logger: fake_service)

    exit_code = cli.main()
    assert exit_code == 3
