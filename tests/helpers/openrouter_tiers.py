"""Test-only OpenRouter model tier resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenRouterTier:
    name: str
    env_var: str
    default_model: str


TIERS: dict[str, OpenRouterTier] = {
    "weak": OpenRouterTier(
        name="weak",
        env_var="OPENROUTER_MODEL_WEAK",
        default_model="meta-llama/llama-3.1-8b-instruct",
    ),
    "mid": OpenRouterTier(
        name="mid",
        env_var="OPENROUTER_MODEL_MID",
        default_model="deepseek/deepseek-v4-pro",
    ),
    "strong": OpenRouterTier(
        name="strong",
        env_var="OPENROUTER_MODEL_STRONG",
        default_model="deepseek/deepseek-v4-pro",
    ),
    "strong-reasoning": OpenRouterTier(
        name="strong-reasoning",
        env_var="OPENROUTER_MODEL_STRONG_REASONING",
        default_model="openai/o4-mini",
    ),
    "tool-weak": OpenRouterTier(
        name="tool-weak",
        env_var="OPENROUTER_MODEL_TOOL_WEAK",
        default_model="meta-llama/llama-3.1-8b-instruct",
    ),
}


def resolve_model(tier: str, env: dict[str, str] | None = None) -> str:
    """Return the OpenRouter model id for a test-only tier."""

    values = env if env is not None else os.environ
    tier_config = TIERS[tier]
    return values.get(tier_config.env_var, tier_config.default_model)


def selected_tiers(env: dict[str, str] | None = None) -> list[str]:
    """Return smoke or full-matrix tier selection from environment flags."""

    values = env if env is not None else os.environ
    if values.get("GOFR_AGENT_LIVE_LLM_FULL_MATRIX") == "1":
        return list(TIERS)
    return ["mid"]
