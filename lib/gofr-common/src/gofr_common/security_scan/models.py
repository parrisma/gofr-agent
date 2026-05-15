"""Data models for Trivy-based security scanning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class VulnerabilityFinding:
    """Normalized vulnerability finding from Trivy output."""

    vulnerability_id: str
    package_name: str
    installed_version: Optional[str]
    fixed_version: Optional[str]
    severity: str
    title: Optional[str]
    primary_url: Optional[str]
    target: str
    status: Optional[str] = None


@dataclass
class PolicyDecision:
    """Policy decision derived from normalized findings."""

    passed: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class NormalizedScanReport:
    """Stable JSON-serializable scan report."""

    target_image: str
    scanned_at_utc: str
    findings: List[VulnerabilityFinding]
    counts_by_severity: Dict[str, int]
    policy_decision: str
    fail_reasons: List[str]
    trivy_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        target_image: str,
        findings: List[VulnerabilityFinding],
        counts_by_severity: Dict[str, int],
        policy_decision: str,
        fail_reasons: List[str],
        trivy_version: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "NormalizedScanReport":
        return cls(
            target_image=target_image,
            scanned_at_utc=datetime.now(timezone.utc).isoformat(),
            findings=findings,
            counts_by_severity=counts_by_severity,
            policy_decision=policy_decision,
            fail_reasons=fail_reasons,
            trivy_version=trivy_version,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [asdict(item) for item in self.findings]
        return payload
