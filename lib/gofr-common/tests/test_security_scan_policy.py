"""Tests for normalization and policy evaluation."""

from gofr_common.security_scan.normalize import normalize_trivy_json
from gofr_common.security_scan.policy import evaluate_policy


def test_normalize_trivy_json_extracts_findings():
    raw = {
        "Metadata": {"Version": "0.60.0"},
        "Results": [
            {
                "Target": "python:3.11",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-1",
                        "PkgName": "openssl",
                        "InstalledVersion": "1.0.0",
                        "FixedVersion": "1.0.1",
                        "Severity": "HIGH",
                        "Title": "Example vuln",
                        "PrimaryURL": "https://example.invalid/CVE-1",
                    },
                    {
                        "VulnerabilityID": "CVE-2",
                        "PkgName": "libxml",
                        "InstalledVersion": "2.0.0",
                        "FixedVersion": "",
                        "Severity": "CRITICAL",
                    },
                ],
            }
        ],
    }

    findings, counts, trivy_version = normalize_trivy_json(raw, target_image="python:3.11")

    assert trivy_version == "0.60.0"
    assert len(findings) == 2
    assert counts["HIGH"] == 1
    assert counts["CRITICAL"] == 1


def test_policy_fails_for_high_by_default():
    raw = {
        "Results": [
            {
                "Target": "alpine:latest",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-3",
                        "PkgName": "busybox",
                        "Severity": "HIGH",
                        "FixedVersion": "1.1.0",
                    }
                ],
            }
        ]
    }
    findings, _, _ = normalize_trivy_json(raw, target_image="alpine:latest")
    decision = evaluate_policy(findings, fail_on_severity="HIGH", ignore_unfixed=False)
    assert decision.passed is False
    assert decision.reasons


def test_policy_ignore_unfixed_skips_unpatched():
    raw = {
        "Results": [
            {
                "Target": "alpine:latest",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-4",
                        "PkgName": "busybox",
                        "Severity": "HIGH",
                        "FixedVersion": "",
                    }
                ],
            }
        ]
    }
    findings, _, _ = normalize_trivy_json(raw, target_image="alpine:latest")

    decision = evaluate_policy(findings, fail_on_severity="HIGH", ignore_unfixed=True)
    assert decision.passed is True
    assert decision.reasons == []
