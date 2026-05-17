"""Tests for prompt-hardening live runner helper."""

from __future__ import annotations

from tests.helpers.prompt_hardening_runner import live_repetitions, run_repeated_scenario


class TestPromptHardeningRunner:
    def test_repetitions_are_capped_without_override(self) -> None:
        assert live_repetitions({"GOFR_AGENT_LIVE_LLM_REPETITIONS": "99"}) == 10

    def test_repeated_scenario_captures_duration_and_tool_count(self) -> None:
        results = run_repeated_scenario(
            scenario_id="S1",
            model="provider/model",
            repetitions=2,
            call=lambda: {"steps": [{"kind": "tool_call"}]},
        )

        assert len(results) == 2
        assert results[0].tool_call_count == 1
        assert results[1].repetition == 2
