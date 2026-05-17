"""Sanitise untrusted metadata before it reaches model-visible prompts."""

from __future__ import annotations

import re
import unicodedata

DESCRIPTION_CHAR_LIMIT = 500
SERVICE_BLOCK_CHAR_LIMIT = 2048
TOTAL_METADATA_CHAR_LIMIT = 8192

_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff]")
_WHITESPACE_RE = re.compile(r"\s+")
_CYRILLIC_LOOKALIKES = str.maketrans(
    {
        "\u0430": "a",
        "\u0435": "e",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0443": "y",
        "\u0445": "x",
        "\u0456": "i",
    }
)
_INJECTION_RULES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
        r"system\s*:",
        r"developer\s+(message|note)",
        r"override\s+(the\s+)?(policy|instructions|system)",
        r"answer\s+from\s+(your\s+)?(own\s+)?knowledge",
        r"do\s+not\s+use\s+tools",
        r"disable\s+(provenance|grounding|tools)",
    )
)


def normalise_metadata(text: str) -> str:
    """Normalise text for prompt-surface rule matching."""

    normalised = unicodedata.normalize("NFKC", text).translate(_CYRILLIC_LOOKALIKES)
    normalised = _ZERO_WIDTH_RE.sub("", normalised)
    normalised = _WHITESPACE_RE.sub(" ", normalised).strip().lower()
    return normalised


def sanitize_metadata(text: str, *, max_chars: int = DESCRIPTION_CHAR_LIMIT) -> str:
    """Return neutralised, length-bounded metadata text."""

    sanitised = normalise_metadata(text)
    for rule in _INJECTION_RULES:
        sanitised = rule.sub("[filtered metadata]", sanitised)
    if len(sanitised) > max_chars:
        return sanitised[:max_chars].rstrip() + "...[truncated]"
    return sanitised


def quote_capability_metadata(lines: list[str], *, max_chars: int) -> list[str]:
    """Render metadata lines as quoted text within a bounded block."""

    rendered: list[str] = []
    used = 0
    for line in lines:
        quoted = f"> {line}"
        next_used = used + len(quoted) + 1
        if next_used > max_chars:
            rendered.append("> ...[metadata truncated]")
            break
        rendered.append(quoted)
        used = next_used
    return rendered
