"""Simple environment loader with optional .env support.

Loads configuration values in deterministic order:
1) .env file (if provided and exists)
2) OS environment variables
3) Explicit overrides (highest precedence)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, MutableMapping, Optional

from dotenv import dotenv_values


class EnvLoader:
    """Load environment-style key/value pairs with .env support."""

    def __init__(self, env_file: Optional[Path | str] = None) -> None:
        self.env_file = Path(env_file) if env_file else None

    def load(self, overrides: Optional[Mapping[str, str]] = None) -> MutableMapping[str, str]:
        """Load environment data with deterministic precedence.

        Precedence (low -> high): .env file, OS env vars, overrides
        """
        data: MutableMapping[str, str] = {}

        env_path = self.env_file or Path.cwd() / ".env"
        if env_path.exists():
            file_values = dotenv_values(env_path)
            data.update({k: v for k, v in file_values.items() if v is not None})

        data.update(os.environ)

        if overrides:
            data.update({k: str(v) for k, v in overrides.items()})

        return data


__all__ = ["EnvLoader"]
