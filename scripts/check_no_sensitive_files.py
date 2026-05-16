#!/usr/bin/env python3
"""Block obviously sensitive local artefacts from being committed."""

from __future__ import annotations

import sys
from pathlib import PurePath

BLOCKED_DIRECTORIES = frozenset(
    {
        "secrets",
        "certs",
        "certificates",
        ".direnv",
    }
)

BLOCKED_FILENAMES = frozenset(
    {
        ".env",
        ".envrc",
        ".netrc",
        ".vault-token",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "vault_root_token",
        "vault_unseal_key",
        "vault_creds",
    }
)

BLOCKED_SUFFIXES = frozenset(
    {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".jks",
        ".keystore",
        ".kdbx",
        ".crt",
        ".cer",
        ".csr",
        ".der",
        ".p7b",
        ".p7c",
        ".p8",
        ".pk8",
        ".mobileprovision",
        ".provisionprofile",
        ".ovpn",
        ".credentials",
        ".creds",
        ".secret",
        ".secrets",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".dump",
    }
)

ALLOWED_SUFFIX_SUFFIXES = (
    ".example",
    ".sample",
    ".template",
    ".dist",
)


def _normalise(path_str: str) -> PurePath:
    return PurePath(path_str.replace("\\", "/"))


def _is_allowlisted(path: PurePath) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in ALLOWED_SUFFIX_SUFFIXES)


def find_violations(paths: list[str]) -> list[str]:
    violations: list[str] = []
    for raw_path in paths:
        path = _normalise(raw_path)
        lower_parts = [part.lower() for part in path.parts]
        lower_name = path.name.lower()

        if _is_allowlisted(path):
            continue

        blocked_dir = next((part for part in lower_parts if part in BLOCKED_DIRECTORIES), None)
        if blocked_dir is not None:
            violations.append(f"{raw_path}: blocked sensitive directory '{blocked_dir}'")
            continue

        if lower_name in BLOCKED_FILENAMES:
            violations.append(f"{raw_path}: blocked sensitive filename '{lower_name}'")
            continue

        suffixes = [suffix.lower() for suffix in path.suffixes]
        blocked_suffix = next((suffix for suffix in suffixes if suffix in BLOCKED_SUFFIXES), None)
        if blocked_suffix is not None:
            violations.append(f"{raw_path}: blocked sensitive file extension '{blocked_suffix}'")
            continue

        if lower_name.endswith(".token") or lower_name.endswith("_token"):
            violations.append(f"{raw_path}: blocked token-like filename '{lower_name}'")

    return violations


def main(argv: list[str] | None = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    violations = find_violations(paths)
    if not violations:
        return 0

    print("Refusing to commit files that look like credentials, certs, or local secrets:")
    for violation in violations:
        print(f"- {violation}")
    print("Rename templates to *.example or move real secrets to Vault / local secure storage.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
