"""Dataclass-based Settings for GOFR Applications

Provides typed configuration with environment variable support.
All settings classes accept a parameterized env_prefix for project-specific configuration.

Design principles:
- Single source of truth for all configuration
- Environment variable overrides with sensible defaults
- Type-safe settings with validation
- Explicit security requirements (e.g., JWT secret enforcement)
- Test mode support for temporary directories
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from gofr_common.config.env_loader import EnvLoader
from gofr_common.config.ports import get_ports


@dataclass
class ServerSettings:
    """Network server configuration

    Attributes:
        host: Server bind address (default: 0.0.0.0)
        mcp_port: MCP server port
        web_port: Web server port
        mcpo_port: MCPO proxy port
    """

    host: str = "0.0.0.0"
    mcp_port: int = 8001
    web_port: int = 8000
    mcpo_port: int = 8002

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR",
        default_mcp_port: int = 8001,
        default_web_port: int = 8000,
        default_mcpo_port: int = 8002,
        env: Optional[Mapping[str, str]] = None,
    ) -> "ServerSettings":
        """Load server settings from environment variables

        Args:
            prefix: Environment variable prefix (e.g., GOFR_PLOT, GOFR_DOC)
            default_mcp_port: Default MCP port if not set in environment
            default_web_port: Default web port if not set in environment
            default_mcpo_port: Default MCPO port if not set in environment

        Environment variables:
            {prefix}_HOST: Server host
            {prefix}_MCP_PORT: MCP server port
            {prefix}_WEB_PORT: Web server port
            {prefix}_MCPO_PORT: MCPO proxy port
        """
        env_data = env or os.environ

        return cls(
            host=env_data.get(f"{prefix}_HOST", "0.0.0.0"),
            mcp_port=int(env_data.get(f"{prefix}_MCP_PORT", str(default_mcp_port))),
            web_port=int(env_data.get(f"{prefix}_WEB_PORT", str(default_web_port))),
            mcpo_port=int(env_data.get(f"{prefix}_MCPO_PORT", str(default_mcpo_port))),
        )


@dataclass
class AuthSettings:
    """Authentication and security configuration

    Attributes:
        jwt_secret: JWT signing secret (required if require_auth=True)
        token_store_path: Path to token store file (optional)
        require_auth: Whether authentication is required
    """

    jwt_secret: Optional[str] = None
    token_store_path: Optional[Path] = None
    require_auth: bool = True

    def __post_init__(self):
        """Validate authentication settings"""
        if self.require_auth and not self.jwt_secret:
            raise ValueError(
                "JWT secret is required when authentication is enabled. "
                "Set GOFR_JWT_SECRET environment variable or provide via --jwt-secret"
            )

        # Convert string path to Path object
        if isinstance(self.token_store_path, str):
            self.token_store_path = Path(self.token_store_path)

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR",
        require_auth: bool = True,
        env: Optional[Mapping[str, str]] = None,
    ) -> "AuthSettings":
        """Load auth settings from environment variables

        Args:
            prefix: Environment variable prefix
            require_auth: Whether authentication is required

        Environment variables:
            GOFR_JWT_SECRET: JWT secret key (system-wide, shared across services)
            {prefix}_TOKEN_STORE: Token store path
        """
        env_data = env or os.environ

        jwt_secret = env_data.get("GOFR_JWT_SECRET")
        token_store = env_data.get(f"{prefix}_TOKEN_STORE")

        return cls(
            jwt_secret=jwt_secret,
            token_store_path=Path(token_store) if token_store else None,
            require_auth=require_auth,
        )

    def get_secret_fingerprint(self) -> str:
        """Get SHA256 fingerprint of JWT secret for logging (first 12 chars)"""
        if not self.jwt_secret:
            return "none"
        import hashlib

        return f"sha256:{hashlib.sha256(self.jwt_secret.encode()).hexdigest()[:12]}"


@dataclass
class StorageSettings:
    """Data persistence configuration

    Attributes:
        data_dir: Base data directory
        storage_dir: Directory for file storage
        auth_dir: Directory for authentication data
        sessions_dir: Directory for session data (optional)
        proxy_dir: Directory for proxy data (optional)
    """

    data_dir: Path
    storage_dir: Path
    auth_dir: Path
    sessions_dir: Optional[Path] = None
    proxy_dir: Optional[Path] = None

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR",
        project_root: Optional[Path] = None,
        test_mode: bool = False,
        env: Optional[Mapping[str, str]] = None,
    ) -> "StorageSettings":
        """Load storage settings from environment variables

        Args:
            prefix: Environment variable prefix
            project_root: Project root directory for default data location
            test_mode: Whether in test mode (currently unused, for future expansion)

        Environment variables:
            {prefix}_DATA_DIR: Base data directory
        """
        # Check environment variable first
        env_data = env or os.environ

        env_data_dir = env_data.get(f"{prefix}_DATA_DIR")
        if env_data_dir:
            data_dir = Path(env_data_dir)
        elif project_root:
            data_dir = project_root / "data"
        else:
            # Fallback to current directory
            data_dir = Path.cwd() / "data"

        return cls(
            data_dir=data_dir,
            storage_dir=data_dir / "storage",
            auth_dir=data_dir / "auth",
            sessions_dir=data_dir / "sessions",
            proxy_dir=data_dir / "storage",  # Same as storage by default
        )

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        if self.sessions_dir:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def get_token_store_path(self) -> Path:
        """Get the path to the token store file"""
        return self.auth_dir / "tokens.json"

    def get_public_storage_dir(self) -> Path:
        """Get the public storage directory"""
        return self.storage_dir / "public"


@dataclass
class LogSettings:
    """Logging configuration

    Attributes:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format: Log format (console, json, structured)
    """

    level: str = "INFO"
    format: str = "console"  # console, json, or structured

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR",
        env: Optional[Mapping[str, str]] = None,
    ) -> "LogSettings":
        """Load logging settings from environment variables

        Environment variables:
            {prefix}_LOG_LEVEL: Logging level
            {prefix}_LOG_FORMAT: Log format
        """
        env_data = env or os.environ

        return cls(
            level=env_data.get(f"{prefix}_LOG_LEVEL", "INFO").upper(),
            format=env_data.get(f"{prefix}_LOG_FORMAT", "console").lower(),
        )


@dataclass
class Settings:
    """Complete application settings

    Aggregates all configuration domains into a single, typed settings object.
    Can be constructed from environment variables or explicit parameters.

    Attributes:
        server: Network server settings
        auth: Authentication settings
        storage: Data persistence settings
        log: Logging settings
        prefix: Environment variable prefix used
    """

    server: ServerSettings = field(default_factory=ServerSettings)
    auth: AuthSettings = field(
        default_factory=lambda: AuthSettings(jwt_secret=None, require_auth=False)
    )
    storage: StorageSettings = field(default_factory=lambda: StorageSettings.from_env())
    log: LogSettings = field(default_factory=LogSettings)
    prefix: str = "GOFR"

    @classmethod
    def from_env(
        cls,
        prefix: str = "GOFR",
        require_auth: bool = True,
        project_root: Optional[Path] = None,
        default_mcp_port: int = 8001,
        default_web_port: int = 8000,
        default_mcpo_port: int = 8002,
        env_file: Optional[Path] = None,
    ) -> "Settings":
        """
        Load complete settings from environment variables

        Args:
            prefix: Environment variable prefix (default: GOFR)
            require_auth: Whether authentication is required (default: True)
            project_root: Project root for default data directory
            default_mcp_port: Default MCP port
            default_web_port: Default web port
            default_mcpo_port: Default MCPO port

        Returns:
            Settings object populated from environment

        Environment variables:
            {prefix}_HOST: Server host (default: 0.0.0.0)
            {prefix}_MCP_PORT: MCP server port
            {prefix}_WEB_PORT: Web server port
            {prefix}_MCPO_PORT: MCPO proxy port
            GOFR_JWT_SECRET: JWT secret key (system-wide, required if auth enabled)
            {prefix}_TOKEN_STORE: Token store path
            {prefix}_DATA_DIR: Data directory
            {prefix}_LOG_LEVEL: Logging level (default: INFO)
            {prefix}_LOG_FORMAT: Log format (default: console)
        """
        env_data = EnvLoader(env_file).load()

        # Try to resolve defaults from standardized ports if using default values
        if default_mcp_port == 8001 and default_web_port == 8000 and default_mcpo_port == 8002:
            try:
                # Convert prefix (e.g., GOFR_DOC) to service name (e.g., gofr-doc)
                service_name = prefix.lower().replace("_", "-")
                ports = get_ports(service_name, env=env_data)
                default_mcp_port = ports.mcp
                default_mcpo_port = ports.mcpo
                default_web_port = ports.web
            except KeyError:
                # Prefix doesn't match a registered service, stick with defaults
                pass

        return cls(
            server=ServerSettings.from_env(
                prefix, default_mcp_port, default_web_port, default_mcpo_port, env=env_data
            ),
            auth=AuthSettings.from_env(prefix, require_auth, env=env_data),
            storage=StorageSettings.from_env(prefix, project_root, env=env_data),
            log=LogSettings.from_env(prefix, env=env_data),
            prefix=prefix,
        )

    def resolve_defaults(self) -> None:
        """
        Resolve any missing configuration with intelligent defaults

        - If token_store_path is None, use {storage.auth_dir}/tokens.json
        - Ensure all storage directories exist
        """
        # Ensure storage directories exist
        self.storage.ensure_directories()

        # Default token store to standard location if not specified
        if self.auth.token_store_path is None:
            self.auth.token_store_path = self.storage.get_token_store_path()

    def validate(self) -> None:
        """
        Validate settings for consistency and security

        Raises:
            ValueError: If settings are invalid or insecure
        """
        # Auth validation is handled in AuthSettings.__post_init__
        pass


# Global settings storage per prefix
_global_settings: dict[str, Settings] = {}


def get_settings(
    prefix: str = "GOFR",
    reload: bool = False,
    require_auth: bool = True,
    project_root: Optional[Path] = None,
    env_file: Optional[Path] = None,
) -> Settings:
    """
    Get or create settings instance for a given prefix

    Args:
        prefix: Environment variable prefix
        reload: If True, reload settings from environment
        require_auth: Whether authentication is required
        project_root: Project root for default data directory

    Returns:
        Settings instance for the given prefix
    """
    global _global_settings

    if prefix not in _global_settings or reload:
        _global_settings[prefix] = Settings.from_env(
            prefix=prefix,
            require_auth=require_auth,
            project_root=project_root,
            env_file=env_file,
        )
        _global_settings[prefix].resolve_defaults()
        _global_settings[prefix].validate()

    return _global_settings[prefix]


def reset_settings(prefix: Optional[str] = None) -> None:
    """Reset settings (primarily for testing)

    Args:
        prefix: Specific prefix to reset, or None to reset all
    """
    global _global_settings
    if prefix:
        _global_settings.pop(prefix, None)
    else:
        _global_settings.clear()
