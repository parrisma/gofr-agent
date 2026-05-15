import io
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from gofr_common.vault.secrets_discovery import (
    discover_vault_bootstrap_artifacts_validated,
    validate_vault_token,
)


class _DummyResponse:
    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url=url,
        code=code,
        msg="HTTPError",
        hdrs=None,
        fp=io.BytesIO(b"{}"),
    )


def test_validate_vault_token_true_on_200():
    with patch.object(urllib.request, "urlopen", return_value=_DummyResponse(status=200)):
        assert validate_vault_token("http://gofr-vault:8201", "token") is True


def test_validate_vault_token_false_on_403():
    def side_effect(req, timeout=None):
        raise _http_error(req.full_url, 403)

    with patch.object(urllib.request, "urlopen", side_effect=side_effect):
        assert validate_vault_token("http://gofr-vault:8201", "token") is False


def test_discover_validated_returns_none_when_vault_unreachable(tmp_path: Path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "vault_root_token").write_text("token", encoding="utf-8")
    (secrets_dir / "vault_unseal_key").write_text("unseal", encoding="utf-8")

    def side_effect(req, timeout=None):
        raise urllib.error.URLError("unreachable")

    with patch.object(urllib.request, "urlopen", side_effect=side_effect):
        assert (
            discover_vault_bootstrap_artifacts_validated(
                project_root=tmp_path, vault_url="http://gofr-vault:8201"
            )
            is None
        )


def test_discover_validated_returns_artifacts_when_token_valid(tmp_path: Path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "vault_root_token").write_text("token", encoding="utf-8")
    (secrets_dir / "vault_unseal_key").write_text("unseal", encoding="utf-8")

    def side_effect(req, timeout=None):
        if req.full_url.endswith("/v1/sys/health"):
            raise _http_error(req.full_url, 503)
        if req.full_url.endswith("/v1/auth/token/lookup-self"):
            return _DummyResponse(status=200)
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch.object(urllib.request, "urlopen", side_effect=side_effect):
        artifacts = discover_vault_bootstrap_artifacts_validated(
            project_root=tmp_path, vault_url="http://gofr-vault:8201"
        )
        assert artifacts is not None
        assert artifacts.root_token_file == secrets_dir / "vault_root_token"


def test_discover_validated_returns_none_when_token_invalid(tmp_path: Path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "vault_root_token").write_text("token", encoding="utf-8")
    (secrets_dir / "vault_unseal_key").write_text("unseal", encoding="utf-8")

    def side_effect(req, timeout=None):
        if req.full_url.endswith("/v1/sys/health"):
            return _DummyResponse(status=200)
        if req.full_url.endswith("/v1/auth/token/lookup-self"):
            raise _http_error(req.full_url, 403)
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch.object(urllib.request, "urlopen", side_effect=side_effect):
        assert (
            discover_vault_bootstrap_artifacts_validated(
                project_root=tmp_path, vault_url="http://gofr-vault:8201"
            )
            is None
        )
