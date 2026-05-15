"""Core configuration classes for GOFR services.

Provides BaseConfig for environment-aware defaults and InfrastructureConfig for
shared infrastructure dependencies (Vault, Neo4j, ChromaDB, shared secrets).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gofr_common.config.env_loader import EnvLoader

_ALLOWED_ENVS = {"DEV", "TEST", "PROD"}
_ALLOWED_LOG_FORMATS = {"console", "json"}


def _parse_optional_int(value: Optional[str], name: str) -> Optional[int]:
    """Convert optional string to int, raising a clear error when invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


@dataclass
class BaseConfig:
    """Base configuration shared across GOFR services."""

    env: str = "DEV"
    project_root: Path = field(default_factory=Path.cwd)
    log_level: str = "INFO"
    log_format: str = "console"
    prefix: str = "GOFR"

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR",
        project_root: Optional[Path] = None,
        env_file: Optional[Path] = None,
    ) -> "BaseConfig":
        env_data = EnvLoader(env_file).load()

        env_value = env_data.get(f"{prefix}_ENV", env_data.get("GOFR_ENV", "DEV"))
        project_root_value = project_root or env_data.get(f"{prefix}_PROJECT_ROOT")
        resolved_project_root = Path(project_root_value) if project_root_value else Path.cwd()
        log_level = env_data.get(f"{prefix}_LOG_LEVEL", "INFO")
        log_format = env_data.get(f"{prefix}_LOG_FORMAT", "console")

        return cls(
            env=env_value,
            project_root=resolved_project_root,
            log_level=log_level,
            log_format=log_format,
            prefix=prefix,
        )

    def __post_init__(self) -> None:
        self.project_root = Path(self.project_root)
        self.env = self.env.upper()
        self.log_format = self.log_format.lower()
        self.validate()

    @property
    def is_prod(self) -> bool:
        return self.env == "PROD"

    @property
    def is_test(self) -> bool:
        return self.env == "TEST"

    @property
    def is_dev(self) -> bool:
        return self.env == "DEV"

    def validate(self) -> None:
        if self.env not in _ALLOWED_ENVS:
            raise ValueError(f"Invalid environment '{self.env}'. Expected one of {_ALLOWED_ENVS}.")

        if self.log_format not in _ALLOWED_LOG_FORMATS:
            raise ValueError(
                f"Invalid log format '{self.log_format}'. Expected one of {_ALLOWED_LOG_FORMATS}."
            )

        # Normalize log level casing for consistency
        self.log_level = self.log_level.upper()


@dataclass
class InfrastructureConfig(BaseConfig):
    """Infrastructure configuration for shared dependencies."""

    vault_url: Optional[str] = None
    vault_token: Optional[str] = None
    vault_role_id: Optional[str] = None
    vault_secret_id: Optional[str] = None
    vault_path_prefix: str = "gofr/auth"
    vault_mount_point: str = "secret"
    chroma_host: Optional[str] = None
    chroma_port: Optional[int] = None
    neo4j_host: Optional[str] = None
    neo4j_bolt_port: Optional[int] = None
    neo4j_http_port: Optional[int] = None
    shared_jwt_secret: Optional[str] = None

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR",
        project_root: Optional[Path] = None,
        env_file: Optional[Path] = None,
    ) -> "InfrastructureConfig":
        base_config = BaseConfig.from_env(
            prefix=prefix, project_root=project_root, env_file=env_file
        )
        env_data = EnvLoader(env_file).load()

        chroma_host = env_data.get(f"{prefix}_CHROMA_HOST") or env_data.get(
            f"{prefix}_CHROMADB_HOST"
        )
        chroma_port = _parse_optional_int(
            env_data.get(f"{prefix}_CHROMA_PORT"), f"{prefix}_CHROMA_PORT"
        )
        if chroma_port is None:
            chroma_port = _parse_optional_int(
                env_data.get(f"{prefix}_CHROMADB_PORT"), f"{prefix}_CHROMADB_PORT"
            )

        # Vault is shared infrastructure, but callers may prefer a project-specific
        # env prefix (Option A). Prefer `prefix` and fall back to GOFR_* for
        # backwards compatibility.
        vault_prefix = prefix
        return cls(
            env=base_config.env,
            project_root=base_config.project_root,
            log_level=base_config.log_level,
            log_format=base_config.log_format,
            prefix=prefix,
            vault_url=env_data.get(f"{vault_prefix}_VAULT_URL") or env_data.get("GOFR_VAULT_URL"),
            vault_token=env_data.get(f"{vault_prefix}_VAULT_TOKEN") or env_data.get("GOFR_VAULT_TOKEN"),
            vault_role_id=env_data.get(f"{vault_prefix}_VAULT_ROLE_ID") or env_data.get("GOFR_VAULT_ROLE_ID"),
            vault_secret_id=env_data.get(f"{vault_prefix}_VAULT_SECRET_ID") or env_data.get("GOFR_VAULT_SECRET_ID"),
            vault_path_prefix=(
                env_data.get(f"{vault_prefix}_VAULT_PATH_PREFIX")
                or env_data.get("GOFR_VAULT_PATH_PREFIX")
                or "gofr/auth"
            ),
            vault_mount_point=(
                env_data.get(f"{vault_prefix}_VAULT_MOUNT_POINT")
                or env_data.get("GOFR_VAULT_MOUNT_POINT")
                or "secret"
            ),
            chroma_host=chroma_host,
            chroma_port=chroma_port,
            neo4j_host=env_data.get(f"{prefix}_NEO4J_HOST"),
            neo4j_bolt_port=_parse_optional_int(
                env_data.get(f"{prefix}_NEO4J_BOLT_PORT"), f"{prefix}_NEO4J_BOLT_PORT"
            ),
            neo4j_http_port=_parse_optional_int(
                env_data.get(f"{prefix}_NEO4J_HTTP_PORT"), f"{prefix}_NEO4J_HTTP_PORT"
            ),
            shared_jwt_secret=env_data.get("GOFR_JWT_SECRET"),
        )

    def __post_init__(self) -> None:
        super().__post_init__()

        self.chroma_port = _parse_optional_int(
            str(self.chroma_port) if self.chroma_port is not None else None,
            "chroma_port",
        )
        self.neo4j_bolt_port = _parse_optional_int(
            str(self.neo4j_bolt_port) if self.neo4j_bolt_port is not None else None,
            "neo4j_bolt_port",
        )
        self.neo4j_http_port = _parse_optional_int(
            str(self.neo4j_http_port) if self.neo4j_http_port is not None else None,
            "neo4j_http_port",
        )

    def validate(self) -> None:
        super().validate()

        if self.is_prod:
            if not self.vault_url:
                raise ValueError("Vault URL required when env=PROD.")
            if not (self.vault_token or (self.vault_role_id and self.vault_secret_id)):
                # VaultIdentity is supported via a mounted JSON file.
                # If present, runtime auth can use it without env creds.
                if not Path("/run/secrets/vault_creds").exists():
                    raise ValueError(
                        "Vault token or AppRole credentials required when env=PROD."
                    )
