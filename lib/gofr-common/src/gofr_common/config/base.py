"""Legacy Config Class for Backward Compatibility

Provides the Config class pattern used in gofr-np, gofr-dig, gofr-doc.
This wraps the new Settings system to maintain existing API.

Example:
    from gofr_common.config import Config

    # Get paths
    data_dir = Config.get_data_dir()
    storage_dir = Config.get_storage_dir()

    # Test mode
    Config.set_test_mode(test_data_dir=Path("/tmp/test"))
    try:
        # run tests
        pass
    finally:
        Config.clear_test_mode()
"""

import os
from pathlib import Path
from typing import Optional


class Config:
    """Application configuration with support for testing overrides

    This class provides a simple interface for accessing configuration paths.
    It supports test mode for using temporary directories during testing.

    Class Attributes:
        _test_mode: Whether test mode is enabled
        _test_data_dir: Custom data directory for test mode
        _env_prefix: Environment variable prefix (default: GOFR)
    """

    _test_mode: bool = False
    _test_data_dir: Optional[Path] = None
    _env_prefix: str = "GOFR"

    @classmethod
    def set_env_prefix(cls, prefix: str) -> None:
        """Set the environment variable prefix

        Args:
            prefix: Environment variable prefix (e.g., GOFR_PLOT, GOFR_DOC)
        """
        cls._env_prefix = prefix

    @classmethod
    def get_data_dir(cls) -> Path:
        """Get the data directory for persistent storage

        Returns:
            Path to data directory (configurable via {prefix}_DATA_DIR environment variable)

        Default locations:
            - Production: {project_root}/data
            - Testing: Temporary directory set by tests
            - Docker: Can be overridden via {prefix}_DATA_DIR env var
        """
        if cls._test_mode and cls._test_data_dir:
            return cls._test_data_dir

        # Check environment variable for data directory
        env_data_dir = os.environ.get(f"{cls._env_prefix}_DATA_DIR")
        if env_data_dir:
            return Path(env_data_dir)

        # Default to current working directory /data
        # In practice, projects should set _env_prefix and env var
        return Path.cwd() / "data"

    @classmethod
    def get_storage_dir(cls) -> Path:
        """Get the directory for file storage

        Returns:
            Path to storage directory within data folder
        """
        return cls.get_data_dir() / "storage"

    @classmethod
    def get_sessions_dir(cls) -> Path:
        """Get the directory for session storage

        Returns:
            Path to sessions directory within data folder
        """
        return cls.get_data_dir() / "sessions"

    @classmethod
    def get_proxy_dir(cls) -> Path:
        """Get the directory for proxy-stored data

        Returns:
            Path to proxy directory (defaults to storage)
        """
        return cls.get_data_dir() / "storage"

    @classmethod
    def get_auth_dir(cls) -> Path:
        """Get the directory for authentication data

        Returns:
            Path to auth directory within data folder
        """
        return cls.get_data_dir() / "auth"

    @classmethod
    def get_token_store_path(cls) -> Path:
        """Get the path to the token store file

        Returns:
            Path to token store JSON file
        """
        return cls.get_auth_dir() / "tokens.json"

    @classmethod
    def set_test_mode(cls, test_data_dir: Optional[Path] = None) -> None:
        """Enable test mode with optional custom data directory

        Args:
            test_data_dir: Optional path to use for test data
        """
        cls._test_mode = True
        cls._test_data_dir = test_data_dir

    @classmethod
    def clear_test_mode(cls) -> None:
        """Disable test mode and return to normal configuration"""
        cls._test_mode = False
        cls._test_data_dir = None

    @classmethod
    def is_test_mode(cls) -> bool:
        """Check if currently in test mode

        Returns:
            True if test mode is enabled
        """
        return cls._test_mode


def create_config_class(env_prefix: str) -> type:
    """Factory function to create a Config class with a specific env prefix

    Args:
        env_prefix: Environment variable prefix (e.g., GOFR_PLOT)

    Returns:
        A Config class configured with the specified prefix

    Example:
        PlotConfig = create_config_class("GOFR_PLOT")
        data_dir = PlotConfig.get_data_dir()
    """

    class ProjectConfig(Config):
        _env_prefix = env_prefix

    return ProjectConfig


# Convenience functions for backward compatibility
def get_default_storage_dir() -> str:
    """Get default storage directory as string"""
    return str(Config.get_storage_dir())


def get_default_token_store_path() -> str:
    """Get default token store path as string"""
    return str(Config.get_token_store_path())


def get_default_sessions_dir() -> str:
    """Get default sessions directory as string"""
    return str(Config.get_sessions_dir())


def get_default_proxy_dir() -> str:
    """Get default proxy directory as string"""
    return str(Config.get_proxy_dir())


def get_public_storage_dir() -> str:
    """Get public storage directory as string"""
    return str(Config.get_storage_dir() / "public")
