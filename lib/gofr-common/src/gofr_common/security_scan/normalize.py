"""Normalization from Trivy JSON to stable report structure."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import VulnerabilityFinding


def normalize_trivy_json(raw: Dict[str, Any], target_image: str) -> Tuple[List[VulnerabilityFinding], Dict[str, int], str | None]:
    """Normalize raw Trivy JSON into findings and severity counts."""
    findings: List[VulnerabilityFinding] = []
    counts: Dict[str, int] = {
        "UNKNOWN": 0,
        "LOW": 0,
        "MEDIUM": 0,
        "HIGH": 0,
        "CRITICAL": 0,
    }

    for result in raw.get("Results", []):
        result_target = result.get("Target", target_image)
        vulnerabilities = result.get("Vulnerabilities") or []

        for vuln in vulnerabilities:
            severity = (vuln.get("Severity") or "UNKNOWN").upper()
            if severity not in counts:
                severity = "UNKNOWN"
            counts[severity] += 1
            findings.append(
                VulnerabilityFinding(
                    vulnerability_id=vuln.get("VulnerabilityID") or "UNKNOWN",
                    package_name=vuln.get("PkgName") or "UNKNOWN",
                    installed_version=vuln.get("InstalledVersion"),
                    fixed_version=vuln.get("FixedVersion"),
                    severity=severity,
                    title=vuln.get("Title"),
                    primary_url=vuln.get("PrimaryURL"),
                    target=result_target,
                    status=vuln.get("Status"),
                )
            )

    trivy_version = raw.get("Metadata", {}).get("Version")
    return findings, counts, trivy_version
