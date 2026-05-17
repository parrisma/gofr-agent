"""Small live-scenario repetition and budget helper."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScenarioRunResult:
    scenario_id: str
    repetition: int
    model: str
    duration_ms: int
    tool_call_count: int
    payload: dict[str, Any]


def live_repetitions(env: dict[str, str] | None = None) -> int:
    values = env if env is not None else os.environ
    raw = values.get("GOFR_AGENT_LIVE_LLM_REPETITIONS", "3")
    repetitions = int(raw)
    if values.get("GOFR_AGENT_LIVE_LLM_BUDGET_OVERRIDE") == "1":
        return max(1, repetitions)
    return max(1, min(repetitions, 10))


def run_repeated_scenario(
    *,
    scenario_id: str,
    model: str,
    repetitions: int,
    call: Callable[[], dict[str, Any]],
) -> list[ScenarioRunResult]:
    results: list[ScenarioRunResult] = []
    for repetition in range(1, repetitions + 1):
        started_at = time.perf_counter()
        payload = call()
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        tool_call_count = sum(
            1 for step in payload.get("steps", []) if step.get("kind") == "tool_call"
        )
        results.append(
            ScenarioRunResult(
                scenario_id=scenario_id,
                repetition=repetition,
                model=model,
                duration_ms=duration_ms,
                tool_call_count=tool_call_count,
                payload=payload,
            )
        )
    return results
