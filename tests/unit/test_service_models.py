"""Tests for app.services ServiceConfig and ServicesManifest."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services import ServiceConfig, ServicesManifest


class TestServiceConfig:
    def test_valid_http_url(self) -> None:
        cfg = ServiceConfig(name="plot", url="http://localhost:8050/mcp")
        assert cfg.url == "http://localhost:8050/mcp"

    def test_valid_https_url(self) -> None:
        cfg = ServiceConfig(name="plot", url="https://example.com/mcp")
        assert cfg.url == "https://example.com/mcp"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            ServiceConfig(name="bad", url="ftp://nope")

    def test_defaults(self) -> None:
        cfg = ServiceConfig(name="x", url="http://x/mcp")
        assert cfg.token is None
        assert cfg.token_env is None
        assert cfg.description == ""
        assert cfg.enabled is True
        assert cfg.timeout_s == 30.0
        assert cfg.pool_size is None

    def test_token_env_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_SVC_TOKEN", "tok123")
        cfg = ServiceConfig(name="s", url="http://s/mcp", token_env="MY_SVC_TOKEN")
        assert cfg.token == "tok123"

    def test_token_env_not_set_gives_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        cfg = ServiceConfig(name="s", url="http://s/mcp", token_env="MISSING_TOKEN")
        assert cfg.token is None

    def test_disabled_service_parses(self) -> None:
        cfg = ServiceConfig(name="offline-svc", url="http://off/mcp", enabled=False)
        assert cfg.enabled is False


class TestServicesManifestFromYaml:
    def test_round_trip(self, tmp_path: Path) -> None:
        yml = tmp_path / "services.yml"
        yml.write_text(
            "services:\n"
            "  - name: plot\n"
            "    url: http://localhost:8050/mcp\n"
            "    description: Chart rendering\n"
        )
        manifest = ServicesManifest.from_yaml(yml)
        assert len(manifest.services) == 1
        assert manifest.services[0].name == "plot"
        assert manifest.services[0].description == "Chart rendering"

    def test_empty_yaml(self, tmp_path: Path) -> None:
        yml = tmp_path / "empty.yml"
        yml.write_text("")
        manifest = ServicesManifest.from_yaml(yml)
        assert manifest.services == []

    def test_missing_url_raises(self, tmp_path: Path) -> None:
        yml = tmp_path / "bad.yml"
        yml.write_text("services:\n  - name: broken\n    url: ftp://bad\n")
        with pytest.raises(ValidationError):
            ServicesManifest.from_yaml(yml)

    def test_top_level_list_format(self, tmp_path: Path) -> None:
        yml = tmp_path / "list.yml"
        yml.write_text("- name: iq\n  url: http://localhost:8080/mcp\n")
        manifest = ServicesManifest.from_yaml(yml)
        assert len(manifest.services) == 1

    def test_disabled_service_survives(self, tmp_path: Path) -> None:
        yml = tmp_path / "disabled.yml"
        yml.write_text(
            "services:\n"
            "  - name: offline-svc\n"
            "    url: http://localhost:9000/mcp\n"
            "    enabled: false\n"
        )
        manifest = ServicesManifest.from_yaml(yml)
        assert manifest.services[0].enabled is False


class TestServicesManifestFromEnv:
    def test_single_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOFR_AGENT_SERVICES", "plot")
        monkeypatch.setenv("GOFR_AGENT_PLOT_URL", "http://x/mcp")
        manifest = ServicesManifest.from_env()
        assert len(manifest.services) == 1
        assert manifest.services[0].name == "plot"
        assert manifest.services[0].url == "http://x/mcp"

    def test_empty_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOFR_AGENT_SERVICES", raising=False)
        manifest = ServicesManifest.from_env()
        assert manifest.services == []

    def test_missing_url_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOFR_AGENT_SERVICES", "mystery")
        monkeypatch.delenv("GOFR_AGENT_MYSTERY_URL", raising=False)
        manifest = ServicesManifest.from_env()
        assert manifest.services == []
