# Security Scan Module (`gofr_common.security_scan`)

Shared Trivy-based container vulnerability scanning for GOFR services.

## What it provides
- Standardized Trivy invocation wrapper
- Normalized JSON report schema
- Policy evaluation (`pass` / `fail`)
- CLI entrypoint: `gofr-security-scan`

## Defaults (Phase 1)
- Namespace: `security_scan`
- Severity filter: `CRITICAL,HIGH`
- Fail threshold: `HIGH`
- `ignore-unfixed`: `false`
- Output format: JSON

## Environment variables
Use your project prefix (example: `GOFR_DIG`).

- `{PREFIX}_TRIVY_ENABLED` (default: `true`)
- `{PREFIX}_TRIVY_SEVERITIES` (default: `CRITICAL,HIGH`)
- `{PREFIX}_TRIVY_FAIL_ON_SEVERITY` (default: `HIGH`)
- `{PREFIX}_TRIVY_TIMEOUT_SECONDS` (default: `300`)
- `{PREFIX}_TRIVY_IGNORE_UNFIXED` (default: `false`)
- `{PREFIX}_TRIVY_IGNORE_FILE` (optional)
- `{PREFIX}_TRIVY_REPORT_PATH` (default: `artifacts/trivy-report.json`)

## CLI usage

```bash
gofr-security-scan --image gofr-dig-prod:latest --env-prefix GOFR_DIG
```

Optional explicit report path:

```bash
gofr-security-scan --image gofr-dig-prod:latest --env-prefix GOFR_DIG --report-path artifacts/security/trivy-report.json
```

Exit codes:
- `0` policy pass
- `2` policy fail
- `3` execution/configuration error

## Python usage

```python
from gofr_common.security_scan import SecurityScanConfig, SecurityScanService

config = SecurityScanConfig.from_env("GOFR_DIG")
service = SecurityScanService(config=config)
report = service.scan_image("gofr-dig-prod:latest")
service.write_report(report)
```
