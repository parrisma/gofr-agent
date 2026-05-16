from __future__ import annotations

from scripts.check_no_sensitive_files import find_violations


class TestFindViolations:
    def test_allows_example_and_template_suffixes(self) -> None:
        violations = find_violations(
            [
                ".env.example",
                "docs/client.pem.example",
                "docs/sample.key.template",
                "config/dev.env.sample",
            ]
        )

        assert violations == []

    def test_blocks_sensitive_extensions(self) -> None:
        violations = find_violations(
            [
                "client.pem",
                "tls/server.crt",
                "vault/db.sqlite",
                "credentials/app.credentials",
            ]
        )

        assert len(violations) == 4
        assert "client.pem" in violations[0]
        assert ".crt" in violations[1]
        assert ".sqlite" in violations[2]
        assert ".credentials" in violations[3]

    def test_blocks_sensitive_directories_and_filenames(self) -> None:
        violations = find_violations(
            [
                "secrets/config.yml",
                "nested/certs/readme.md",
                ".envrc",
                "keys/id_ed25519",
                "auth/service_token",
            ]
        )

        assert len(violations) == 5
        assert "directory 'secrets'" in violations[0]
        assert "directory 'certs'" in violations[1]
        assert "filename '.envrc'" in violations[2]
        assert "filename 'id_ed25519'" in violations[3]
        assert "token-like filename 'service_token'" in violations[4]
