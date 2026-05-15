import os
from pathlib import Path

import pytest

from gofr_common.config import EnvLoader, get_ports, load_ports, reset_ports_cache


def setup_function() -> None:
    reset_ports_cache()


def teardown_function() -> None:
    reset_ports_cache()


def test_env_loader_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=file\nBAR=file\n")

    monkeypatch.setenv("BAR", "env")

    loader = EnvLoader(env_file)
    data = loader.load({"BAR": "override", "BAZ": "override"})

    assert data["FOO"] == "file"
    assert data["BAR"] == "override"
    assert data["BAZ"] == "override"


def test_ports_use_env_file_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {})
    reset_ports_cache()

    ports = load_ports(force_reload=True)
    assert ports["gofr-iq"].mcp == 8080
    assert ports["gofr-dig"].web == 8072


def test_ports_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"GOFR_IQ_MCP_PORT": "9000"})
    reset_ports_cache()

    ports = get_ports("gofr-iq", env=dict(os.environ))
    assert ports.mcp == 9000
    assert ports.web == 8082  # unchanged defaults
