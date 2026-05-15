"""Policy evaluation for normalized vulnerability findings."""

from __future__ import annotations

from typing import Iterable, List

from .config import fail_severities
from .models import PolicyDecision, VulnerabilityFinding


def evaluate_policy(
    findings: Iterable[VulnerabilityFinding],
    fail_on_severity: str,
    ignore_unfixed: bool,
) -> PolicyDecision:
    """Evaluate pass/fail policy for normalized findings."""
    threshold_set = set(fail_severities(fail_on_severity))

    violations: List[VulnerabilityFinding] = []
    for finding in findings:
        if finding.severity not in threshold_set:
            continue
        if ignore_unfixed and not finding.fixed_version:
            continue
        violations.append(finding)

    if not violations:
        return PolicyDecision(passed=True, reasons=[])

    reasons = []
    for item in violations:
        fixed_part = item.fixed_version or "no-fix-available"
        reasons.append(
            f"{item.severity}:{item.vulnerability_id} pkg={item.package_name} fixed={fixed_part}"
        )

    return PolicyDecision(passed=False, reasons=sorted(set(reasons)))
