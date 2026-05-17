"""Tests for test-only OpenRouter tier resolution."""

from __future__ import annotations

from tests.helpers.openrouter_tiers import resolve_model, selected_tiers


class TestOpenRouterTiers:
    def test_default_smoke_selection_is_mid_only(self) -> None:
        assert selected_tiers({}) == ["mid"]

    def test_full_matrix_selects_all_documented_tiers(self) -> None:
        tiers = selected_tiers({"GOFR_AGENT_LIVE_LLM_FULL_MATRIX": "1"})

        assert tiers == ["weak", "mid", "strong", "strong-reasoning", "tool-weak"]

    def test_env_override_resolves_model(self) -> None:
        model = resolve_model("mid", {"OPENROUTER_MODEL_MID": "provider/model"})

        assert model == "provider/model"
