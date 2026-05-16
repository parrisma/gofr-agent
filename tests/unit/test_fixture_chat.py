"""Tests for scripts.fixture_chat."""

from __future__ import annotations

from unittest.mock import patch

from scripts.fixture_chat import ask_cli, parse_args


def _command_from_run_mock(run_mock: object) -> list[str]:
    call_args = run_mock.call_args  # type: ignore[attr-defined]
    if "args" in call_args.kwargs:
        return call_args.kwargs["args"]
    return call_args.args[0]


class TestParseArgs:
    def test_verbose_flag_is_supported(self) -> None:
        args = parse_args(["--max-steps", "25", "--verbose"])

        assert args.max_steps == 25
        assert args.verbose is True


class TestAskCli:
    def test_ask_cli_forwards_verbose_flag(self) -> None:
        with patch("scripts.fixture_chat.subprocess.run") as run:
            run.return_value.returncode = 0

            exit_code = ask_cli(
                "http://gofr-agent:8090/mcp",
                "fixture-chat",
                "Explain the analytics",
                25,
                verbose=True,
            )

        assert exit_code == 0
        command = _command_from_run_mock(run)
        assert "--verbose" in command
        assert command[-1] == "Explain the analytics"

    def test_ask_cli_omits_verbose_flag_by_default(self) -> None:
        with patch("scripts.fixture_chat.subprocess.run") as run:
            run.return_value.returncode = 0

            exit_code = ask_cli(
                "http://gofr-agent:8090/mcp",
                "fixture-chat",
                "Explain the analytics",
                25,
            )

        assert exit_code == 0
        command = _command_from_run_mock(run)
        assert "--verbose" not in command
        assert command[-1] == "Explain the analytics"
