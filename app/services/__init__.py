"""Service configuration models for gofr-agent.

``ServiceConfig`` represents a single downstream MCP service.
``ServicesManifest`` is the collection loaded from YAML or environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator, model_validator


class ServiceConfig(BaseModel):
    """Configuration for a single downstream MCP service."""

    name: str
    url: str
    token: str | None = None
    token_env: str | None = None
    hub_callback_token: str | None = None
    hub_callback_token_env: str | None = None
    description: str = ""
    enabled: bool = True
    timeout_s: float = 30.0
    pool_size: int | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        # Validate that the URL starts with http:// or https://
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(f"url must start with http:// or https://, got: {v!r}")
        return v

    @model_validator(mode="after")
    def _resolve_token_env(self) -> ServiceConfig:
        """If token_env is set, read the token from that env var."""
        if self.token_env and not self.token:
            self.token = os.environ.get(self.token_env)
        if self.hub_callback_token_env and not self.hub_callback_token:
            self.hub_callback_token = os.environ.get(self.hub_callback_token_env)
        return self

    def safe_dump(self) -> dict[str, Any]:
        """Return a serialisable representation without resolved secret values."""
        return self.model_dump(exclude={"token", "hub_callback_token"})


class ServicesManifest(BaseModel):
    """Collection of downstream service configurations."""

    services: list[ServiceConfig] = []

    @classmethod
    def from_yaml(cls, path: Path) -> ServicesManifest:
        """Load manifest from a YAML file."""
        with open(path) as fh:
            data: Any = yaml.safe_load(fh)
        if data is None:
            return cls(services=[])
        if isinstance(data, dict) and "services" in data:
            return cls.model_validate(data)
        # Accept top-level list format as well
        if isinstance(data, list):
            return cls(services=[ServiceConfig.model_validate(item) for item in data])
        raise ValueError(f"Unexpected YAML structure in {path}")

    @classmethod
    def from_env(cls, prefix: str = "GOFR_AGENT") -> ServicesManifest:
        """Build manifest from env vars.

        Reads ``{PREFIX}_SERVICES=name1,name2`` then for each name reads
        ``{PREFIX}_{NAME_UPPER}_URL``, ``{PREFIX}_{NAME_UPPER}_TOKEN``,
        ``{PREFIX}_{NAME_UPPER}_TOKEN_ENV``, ``{PREFIX}_{NAME_UPPER}_DESCRIPTION``.
        """
        services_raw = os.environ.get(f"{prefix}_SERVICES", "")
        if not services_raw.strip():
            return cls(services=[])

        services: list[ServiceConfig] = []
        for name in services_raw.split(","):
            name = name.strip()
            if not name:
                continue
            key = name.upper().replace("-", "_")
            url = os.environ.get(f"{prefix}_{key}_URL", "")
            if not url:
                continue
            services.append(
                ServiceConfig(
                    name=name,
                    url=url,
                    token=os.environ.get(f"{prefix}_{key}_TOKEN") or None,
                    token_env=os.environ.get(f"{prefix}_{key}_TOKEN_ENV") or None,
                    hub_callback_token=(
                        os.environ.get(f"{prefix}_{key}_HUB_CALLBACK_TOKEN") or None
                    ),
                    hub_callback_token_env=(
                        os.environ.get(f"{prefix}_{key}_HUB_CALLBACK_TOKEN_ENV") or None
                    ),
                    description=os.environ.get(f"{prefix}_{key}_DESCRIPTION", ""),
                    enabled=os.environ.get(f"{prefix}_{key}_ENABLED", "true").lower()
                    not in ("0", "false", "no"),
                    timeout_s=float(os.environ.get(f"{prefix}_{key}_TIMEOUT_S", "30.0")),
                )
            )
        return cls(services=services)
