"""Redacted report helpers for live prompt-hardening runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REDACTION_RULES = (
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"sk-or-[A-Za-z0-9_-]+"),
    re.compile(r"hv[bs]\.[A-Za-z0-9._-]+"),
    re.compile(r"GOFR_PROMPT_HARDENING_PAYLOAD_[A-Z0-9_]+", re.IGNORECASE),
)


def redact_report_text(text: str) -> str:
    redacted = text
    for rule in _REDACTION_RULES:
        redacted = rule.sub("[REDACTED]", redacted)
    return redacted


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    path.write_text(redact_report_text(text), encoding="utf-8")
