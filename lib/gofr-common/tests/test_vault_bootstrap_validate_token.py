from pathlib import Path

from gofr_common.vault.bootstrap import VaultBootstrap, VaultCredentials


def test_auto_init_and_unseal_validate_token_rejects_invalid_loaded_creds(tmp_path: Path, monkeypatch):
    bootstrap = VaultBootstrap(vault_addr="http://gofr-vault:8201")

    monkeypatch.setattr(bootstrap, "wait_for_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        bootstrap,
        "get_status",
        lambda: {
            "http_code": bootstrap.STATUS_HEALTHY,
            "initialized": True,
            "sealed": False,
            "error": None,
        },
    )
    monkeypatch.setattr(
        bootstrap,
        "load_credentials",
        lambda secrets_dir: VaultCredentials(root_token="stale", unseal_key="unseal"),
    )
    monkeypatch.setattr(bootstrap, "_token_valid", lambda token: False)

    success, creds = bootstrap.auto_init_and_unseal(
        secrets_dir=tmp_path, validate_token=True
    )

    assert success is False
    assert creds is not None
