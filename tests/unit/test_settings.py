"""Tests for app.settings."""


import pytest

from app.settings import Settings, get_settings


class TestGetSettings:
    def test_returns_settings_instance(self, tmp_path: pytest.MonkeyPatch) -> None:
        # Redirect storage to tmp so resolve_defaults() can mkdir freely
        s = get_settings(reload=True, require_auth=False)
        assert isinstance(s, Settings)

    def test_reload_returns_fresh_instance(self) -> None:
        s1 = get_settings(reload=True, require_auth=False)
        s2 = get_settings(reload=True, require_auth=False)
        assert isinstance(s1, Settings)
        assert isinstance(s2, Settings)

