"""Tests for app.agent.system_prompt.build_system_prompt."""

from __future__ import annotations

from app.agent.system_prompt import build_system_prompt
from app.services import ServiceConfig
from app.services.discovery import MCPToolInfo


def _svc(name: str, description: str = "") -> ServiceConfig:
    return ServiceConfig(name=name, url=f"http://{name}/mcp", description=description)


def _tool(
    name: str,
    svc: str,
    desc: str = "Does something",
    input_schema: dict | None = None,
) -> MCPToolInfo:
    return MCPToolInfo(
        name=name,
        description=desc,
        input_schema=input_schema or {},
        service_name=svc,
    )


class TestBuildSystemPrompt:
    def test_preamble_always_present(self) -> None:
        prompt = build_system_prompt([], [])
        assert "reasoning agent" in prompt
        assert "tools" in prompt.lower()

    def test_empty_services_note(self) -> None:
        prompt = build_system_prompt([], [])
        assert "No downstream services" in prompt

    def test_service_name_in_prompt(self) -> None:
        prompt = build_system_prompt([_svc("my-service")], [])
        assert "my-service" in prompt

    def test_two_services_both_appear(self) -> None:
        prompt = build_system_prompt(
            [_svc("alpha"), _svc("beta")],
            [_tool("ping", "alpha"), _tool("read", "beta")],
        )
        assert "alpha" in prompt
        assert "beta" in prompt

    def test_tool_names_use_double_underscore(self) -> None:
        prompt = build_system_prompt(
            [_svc("svc-a")],
            [_tool("my_tool", "svc-a")],
        )
        assert "svc-a__my_tool" in prompt

    def test_tool_descriptions_included(self) -> None:
        prompt = build_system_prompt(
            [_svc("svc")],
            [_tool("fetch", "svc", desc="Fetch a page")],
        )
        assert "Fetch a page" in prompt

    def test_service_description_included(self) -> None:
        prompt = build_system_prompt(
            [_svc("svc", description="A great service")],
            [],
        )
        assert "A great service" in prompt

    def test_tool_output_safety_instruction_present(self) -> None:
        prompt = build_system_prompt([], [])
        assert "untrusted data" in prompt
        assert "sentinel blocks" in prompt

    def test_required_arguments_and_bars_hint_included(self) -> None:
        prompt = build_system_prompt(
            [_svc("analytics")],
            [
                _tool(
                    "simple_return",
                    "analytics",
                    desc="Compute simple return from supplied bars.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "bars": {"type": "array"},
                            "window": {"type": "integer"},
                        },
                        "required": ["ticker", "bars"],
                    },
                )
            ],
        )

        assert "Required args: `ticker`, `bars`." in prompt
        assert "Optional args: `window`." in prompt
        assert "fetch OHLCV bars first" in prompt
