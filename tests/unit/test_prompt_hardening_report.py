"""Tests for prompt-hardening report redaction."""

from __future__ import annotations

from tests.helpers.prompt_hardening_report import redact_report_text


class TestPromptHardeningReport:
    def test_redacts_keys_tokens_and_markers(self) -> None:
        text = (
            "Bearer abc.def sk-or-secret hvs.secret "
            "GOFR_PROMPT_HARDENING_PAYLOAD_IGNORE"
        )

        redacted = redact_report_text(text)

        assert "abc.def" not in redacted
        assert "sk-or-secret" not in redacted
        assert "hvs.secret" not in redacted
        assert "GOFR_PROMPT_HARDENING_PAYLOAD_IGNORE" not in redacted
