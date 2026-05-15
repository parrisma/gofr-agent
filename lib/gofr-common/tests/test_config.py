"""Tests for gofr_common.config module"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from gofr_common.config import (
    AuthSettings,
    Config,
    LogSettings,
    ServerSettings,
    Settings,
    StorageSettings,
    get_default_proxy_dir,
    get_default_sessions_dir,
    get_default_storage_dir,
    get_default_token_store_path,
    get_public_storage_dir,
    get_settings,
    reset_settings,
)
from gofr_common.config.base import create_config_class
from gofr_common.config.base_config import BaseConfig, InfrastructureConfig


class TestServerSettings:
    """Tests for ServerSettings dataclass"""

    def test_default_values(self):
        """Test default server settings"""
        settings = ServerSettings()
        assert settings.host == "0.0.0.0"
        assert settings.mcp_port == 8001
        assert settings.web_port == 8000
        assert settings.mcpo_port == 8002

    def test_from_env_default_prefix(self):
        """Test loading from environment with default prefix"""
        with patch.dict(
            os.environ,
            {
                "GOFR_HOST": "127.0.0.1",
                "GOFR_MCP_PORT": "9001",
                "GOFR_WEB_PORT": "9000",
                "GOFR_MCPO_PORT": "9002",
            },
            clear=False,
        ):
            settings = ServerSettings.from_env()
            assert settings.host == "127.0.0.1"
            assert settings.mcp_port == 9001
            assert settings.web_port == 9000
            assert settings.mcpo_port == 9002

    def test_from_env_custom_prefix(self):
        """Test loading from environment with custom prefix"""
        with patch.dict(
            os.environ,
            {
                "GOFR_PLOT_HOST": "localhost",
                "GOFR_PLOT_MCP_PORT": "8050",
                "GOFR_PLOT_WEB_PORT": "8052",
                "GOFR_PLOT_MCPO_PORT": "8051",
            },
            clear=False,
        ):
            settings = ServerSettings.from_env(prefix="GOFR_PLOT")
            assert settings.host == "localhost"
            assert settings.mcp_port == 8050
            assert settings.web_port == 8052
            assert settings.mcpo_port == 8051

    def test_from_env_with_custom_defaults(self):
        """Test custom default ports"""
        settings = ServerSettings.from_env(
            prefix="NONEXISTENT",
            default_mcp_port=8040,
            default_web_port=8042,
            default_mcpo_port=8041,
        )
        assert settings.mcp_port == 8040
        assert settings.web_port == 8042
        assert settings.mcpo_port == 8041


class TestAuthSettings:
    """Tests for AuthSettings dataclass"""

    def test_require_auth_without_secret_raises(self):
        """Test that require_auth=True without secret raises ValueError"""
        with pytest.raises(ValueError, match="JWT secret is required"):
            AuthSettings(require_auth=True, jwt_secret=None)

    def test_no_auth_required_without_secret_ok(self):
        """Test that require_auth=False without secret is OK"""
        settings = AuthSettings(require_auth=False, jwt_secret=None)
        assert settings.jwt_secret is None
        assert settings.require_auth is False

    def test_with_jwt_secret(self):
        """Test with valid JWT secret"""
        settings = AuthSettings(
            require_auth=True,
            jwt_secret="test-secret-key-12345",
        )
        assert settings.jwt_secret == "test-secret-key-12345"
        assert settings.require_auth is True

    def test_token_store_path_string_conversion(self):
        """Test that string paths are converted to Path"""
        settings = AuthSettings(
            require_auth=False,
            token_store_path=Path("/tmp/tokens.json"),
        )
        assert isinstance(settings.token_store_path, Path)
        assert settings.token_store_path == Path("/tmp/tokens.json")

    def test_from_env(self):
        """Test loading from environment"""
        with patch.dict(
            os.environ,
            {
                "GOFR_JWT_SECRET": "env-secret-key",
                "GOFR_DOC_TOKEN_STORE": "/data/tokens.json",
            },
            clear=False,
        ):
            settings = AuthSettings.from_env(prefix="GOFR_DOC", require_auth=True)
            assert settings.jwt_secret == "env-secret-key"
            assert settings.token_store_path == Path("/data/tokens.json")

    def test_get_secret_fingerprint(self):
        """Test JWT secret fingerprint generation"""
        settings = AuthSettings(
            require_auth=True,
            jwt_secret="test-secret",
        )
        fingerprint = settings.get_secret_fingerprint()
        assert fingerprint.startswith("sha256:")
        assert len(fingerprint) == 19  # "sha256:" + 12 hex chars

    def test_get_secret_fingerprint_no_secret(self):
        """Test fingerprint when no secret is set"""
        settings = AuthSettings(require_auth=False, jwt_secret=None)
        assert settings.get_secret_fingerprint() == "none"


class TestStorageSettings:
    """Tests for StorageSettings dataclass"""

    def test_from_env_with_env_var(self):
        """Test loading data dir from environment"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/custom/data",
            },
            clear=False,
        ):
            settings = StorageSettings.from_env()
            assert settings.data_dir == Path("/custom/data")
            assert settings.storage_dir == Path("/custom/data/storage")
            assert settings.auth_dir == Path("/custom/data/auth")

    def test_from_env_with_project_root(self):
        """Test using project root as fallback"""
        # Clear any existing env var
        env = os.environ.copy()
        env.pop("GOFR_DATA_DIR", None)
        with patch.dict(os.environ, env, clear=True):
            settings = StorageSettings.from_env(project_root=Path("/home/user/project"))
            assert settings.data_dir == Path("/home/user/project/data")

    def test_ensure_directories(self):
        """Test directory creation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = StorageSettings(
                data_dir=Path(tmpdir) / "data",
                storage_dir=Path(tmpdir) / "data" / "storage",
                auth_dir=Path(tmpdir) / "data" / "auth",
                sessions_dir=Path(tmpdir) / "data" / "sessions",
            )
            settings.ensure_directories()

            assert settings.data_dir is not None and settings.data_dir.exists()
            assert settings.storage_dir is not None and settings.storage_dir.exists()
            assert settings.auth_dir is not None and settings.auth_dir.exists()
            assert settings.sessions_dir is not None and settings.sessions_dir.exists()

    def test_get_token_store_path(self):
        """Test token store path resolution"""
        settings = StorageSettings(
            data_dir=Path("/data"),
            storage_dir=Path("/data/storage"),
            auth_dir=Path("/data/auth"),
        )
        assert settings.get_token_store_path() == Path("/data/auth/tokens.json")

    def test_get_public_storage_dir(self):
        """Test public storage dir resolution"""
        settings = StorageSettings(
            data_dir=Path("/data"),
            storage_dir=Path("/data/storage"),
            auth_dir=Path("/data/auth"),
        )
        assert settings.get_public_storage_dir() == Path("/data/storage/public")


class TestLogSettings:
    """Tests for LogSettings dataclass"""

    def test_default_values(self):
        """Test default log settings"""
        settings = LogSettings()
        assert settings.level == "INFO"
        assert settings.format == "console"

    def test_from_env(self):
        """Test loading from environment"""
        with patch.dict(
            os.environ,
            {
                "GOFR_LOG_LEVEL": "debug",
                "GOFR_LOG_FORMAT": "JSON",
            },
            clear=False,
        ):
            settings = LogSettings.from_env()
            assert settings.level == "DEBUG"  # uppercased
            assert settings.format == "json"  # lowercased


class TestSettings:
    """Tests for composite Settings dataclass"""

    def test_from_env_no_auth(self):
        """Test loading settings without auth requirement"""
        with patch.dict(
            os.environ,
            {
                "TEST_HOST": "127.0.0.1",
                "TEST_MCP_PORT": "9001",
                "TEST_DATA_DIR": "/test/data",
                "TEST_LOG_LEVEL": "DEBUG",
            },
            clear=False,
        ):
            settings = Settings.from_env(prefix="TEST", require_auth=False)
            assert settings.server.host == "127.0.0.1"
            assert settings.server.mcp_port == 9001
            assert settings.storage.data_dir == Path("/test/data")
            assert settings.log.level == "DEBUG"
            assert settings.prefix == "TEST"

    def test_from_env_with_auth(self):
        """Test loading settings with auth requirement"""
        with patch.dict(
            os.environ,
            {
                "GOFR_JWT_SECRET": "test-secret",
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            settings = Settings.from_env(prefix="GOFR", require_auth=True)
            assert settings.auth.jwt_secret == "test-secret"
            assert settings.auth.require_auth is True

    def test_resolve_defaults(self):
        """Test that resolve_defaults sets token store path"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "GOFR_DATA_DIR": tmpdir,
                },
                clear=False,
            ):
                settings = Settings.from_env(prefix="GOFR", require_auth=False)
                assert settings.auth.token_store_path is None

                settings.resolve_defaults()

                assert settings.auth.token_store_path is not None
                assert settings.auth.token_store_path == Path(tmpdir) / "auth" / "tokens.json"
                assert settings.storage.data_dir.exists()


class TestGetSettings:
    """Tests for get_settings singleton function"""

    def setup_method(self):
        """Reset settings before each test"""
        reset_settings()

    def teardown_method(self):
        """Reset settings after each test"""
        reset_settings()

    def test_get_settings_creates_instance(self):
        """Test that get_settings creates a new instance"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "GOFR_DATA_DIR": tmpdir,
                },
                clear=False,
            ):
                settings = get_settings(prefix="GOFR", require_auth=False)
                assert isinstance(settings, Settings)
                assert settings.storage.data_dir == Path(tmpdir)

    def test_get_settings_returns_same_instance(self):
        """Test that get_settings returns cached instance"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "GOFR_DATA_DIR": tmpdir,
                },
                clear=False,
            ):
                settings1 = get_settings(prefix="GOFR", require_auth=False)
                settings2 = get_settings(prefix="GOFR", require_auth=False)
                assert settings1 is settings2

    def test_get_settings_different_prefixes(self):
        """Test that different prefixes return different instances"""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                with patch.dict(
                    os.environ,
                    {
                        "PREFIX1_DATA_DIR": tmpdir1,
                        "PREFIX2_DATA_DIR": tmpdir2,
                    },
                    clear=False,
                ):
                    settings1 = get_settings(prefix="PREFIX1", require_auth=False)
                    settings2 = get_settings(prefix="PREFIX2", require_auth=False)
                    assert settings1 is not settings2
                    assert settings1.storage.data_dir == Path(tmpdir1)
                    assert settings2.storage.data_dir == Path(tmpdir2)

    def test_get_settings_reload(self):
        """Test that reload=True creates new instance"""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with patch.dict(
                os.environ,
                {
                    "GOFR_DATA_DIR": tmpdir1,
                },
                clear=False,
            ):
                settings1 = get_settings(prefix="GOFR", require_auth=False)

            with tempfile.TemporaryDirectory() as tmpdir2:
                with patch.dict(
                    os.environ,
                    {
                        "GOFR_DATA_DIR": tmpdir2,
                    },
                    clear=False,
                ):
                    settings2 = get_settings(prefix="GOFR", require_auth=False, reload=True)
                    assert settings1 is not settings2
                    assert settings2.storage.data_dir == Path(tmpdir2)

    def test_reset_settings_specific_prefix(self):
        """Test resetting specific prefix"""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                with patch.dict(
                    os.environ,
                    {
                        "P1_DATA_DIR": tmpdir1,
                        "P2_DATA_DIR": tmpdir2,
                    },
                    clear=False,
                ):
                    get_settings(prefix="P1", require_auth=False)
                    s2_original = get_settings(prefix="P2", require_auth=False)

                    reset_settings(prefix="P1")

                    # P2 should still be cached
                    s2_after = get_settings(prefix="P2", require_auth=False)
                    assert s2_original is s2_after


class TestConfig:
    """Tests for legacy Config class"""

    def setup_method(self):
        """Reset Config before each test"""
        Config.clear_test_mode()
        Config._env_prefix = "GOFR"

    def teardown_method(self):
        """Reset Config after each test"""
        Config.clear_test_mode()
        Config._env_prefix = "GOFR"

    def test_get_data_dir_from_env(self):
        """Test getting data dir from environment"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/custom/data",
            },
            clear=False,
        ):
            assert Config.get_data_dir() == Path("/custom/data")

    def test_get_data_dir_custom_prefix(self):
        """Test getting data dir with custom prefix"""
        Config.set_env_prefix("GOFR_PLOT")
        with patch.dict(
            os.environ,
            {
                "GOFR_PLOT_DATA_DIR": "/plot/data",
            },
            clear=False,
        ):
            assert Config.get_data_dir() == Path("/plot/data")

    def test_get_storage_dir(self):
        """Test getting storage dir"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            assert Config.get_storage_dir() == Path("/data/storage")

    def test_get_sessions_dir(self):
        """Test getting sessions dir"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            assert Config.get_sessions_dir() == Path("/data/sessions")

    def test_get_proxy_dir(self):
        """Test getting proxy dir"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            assert Config.get_proxy_dir() == Path("/data/storage")

    def test_get_auth_dir(self):
        """Test getting auth dir"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            assert Config.get_auth_dir() == Path("/data/auth")

    def test_get_token_store_path(self):
        """Test getting token store path"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            assert Config.get_token_store_path() == Path("/data/auth/tokens.json")

    def test_test_mode(self):
        """Test test mode functionality"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            Config.set_test_mode(test_dir)

            assert Config.is_test_mode() is True
            assert Config.get_data_dir() == test_dir
            assert Config.get_storage_dir() == test_dir / "storage"

            Config.clear_test_mode()
            assert Config.is_test_mode() is False


class TestCreateConfigClass:
    """Tests for create_config_class factory"""

    def test_create_config_with_prefix(self):
        """Test creating a config class with custom prefix"""
        PlotConfig = create_config_class("GOFR_PLOT")

        with patch.dict(
            os.environ,
            {
                "GOFR_PLOT_DATA_DIR": "/plot/data",
            },
            clear=False,
        ):
            assert PlotConfig.get_data_dir() == Path("/plot/data")

    def test_multiple_config_classes_independent(self):
        """Test that multiple config classes are independent"""
        PlotConfig = create_config_class("GOFR_PLOT")
        DocConfig = create_config_class("GOFR_DOC")

        with patch.dict(
            os.environ,
            {
                "GOFR_PLOT_DATA_DIR": "/plot/data",
                "GOFR_DOC_DATA_DIR": "/doc/data",
            },
            clear=False,
        ):
            assert PlotConfig.get_data_dir() == Path("/plot/data")
            assert DocConfig.get_data_dir() == Path("/doc/data")


class TestConvenienceFunctions:
    """Tests for convenience functions"""

    def setup_method(self):
        """Reset Config before each test"""
        Config.clear_test_mode()
        Config._env_prefix = "GOFR"

    def teardown_method(self):
        """Reset Config after each test"""
        Config.clear_test_mode()
        Config._env_prefix = "GOFR"

    def test_get_default_storage_dir(self):
        """Test get_default_storage_dir returns string"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            result = get_default_storage_dir()
            assert isinstance(result, str)
            assert result == "/data/storage"

    def test_get_default_token_store_path(self):
        """Test get_default_token_store_path returns string"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            result = get_default_token_store_path()
            assert isinstance(result, str)
            assert result == "/data/auth/tokens.json"

    def test_get_default_sessions_dir(self):
        """Test get_default_sessions_dir returns string"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            result = get_default_sessions_dir()
            assert isinstance(result, str)
            assert result == "/data/sessions"

    def test_get_default_proxy_dir(self):
        """Test get_default_proxy_dir returns string"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            result = get_default_proxy_dir()
            assert isinstance(result, str)
            assert result == "/data/storage"

    def test_get_public_storage_dir(self):
        """Test get_public_storage_dir returns string"""
        with patch.dict(
            os.environ,
            {
                "GOFR_DATA_DIR": "/data",
            },
            clear=False,
        ):
            result = get_public_storage_dir()
            assert isinstance(result, str)
            assert result == "/data/storage/public"


class TestBaseConfig:
    """Tests for BaseConfig"""

    def test_defaults_and_flags(self):
        config = BaseConfig()
        assert config.is_dev is True
        assert config.is_test is False
        assert config.is_prod is False
        assert config.project_root.exists()

    def test_from_env_reads_prefix(self):
        with patch.dict(
            os.environ,
            {
                "GOFR_ENV": "test",
                "GOFR_LOG_LEVEL": "debug",
                "GOFR_LOG_FORMAT": "json",
            },
            clear=False,
        ):
            cfg = BaseConfig.from_env()
            assert cfg.env == "TEST"
            assert cfg.log_level == "DEBUG"
            assert cfg.log_format == "json"

    def test_invalid_env_raises(self):
        with pytest.raises(ValueError):
            BaseConfig(env="LOCAL")


class TestInfrastructureConfig:
    """Tests for InfrastructureConfig"""

    def test_loads_infra_from_env(self):
        with patch.dict(
            os.environ,
            {
                "GOFR_CHROMA_HOST": "chroma.local",
                "GOFR_CHROMA_PORT": "9100",
                "GOFR_NEO4J_HOST": "neo4j.local",
                "GOFR_NEO4J_BOLT_PORT": "7787",
                "GOFR_NEO4J_HTTP_PORT": "7574",
                "GOFR_VAULT_URL": "https://vault.local",
                "GOFR_VAULT_TOKEN": "token",
                "GOFR_VAULT_PATH_PREFIX": "gofr/test",
            },
            clear=False,
        ):
            cfg = InfrastructureConfig.from_env()
            assert cfg.chroma_host == "chroma.local"
            assert cfg.chroma_port == 9100
            assert cfg.neo4j_host == "neo4j.local"
            assert cfg.neo4j_bolt_port == 7787
            assert cfg.neo4j_http_port == 7574
            assert cfg.vault_url == "https://vault.local"
            assert cfg.vault_token == "token"
            assert cfg.vault_path_prefix == "gofr/test"

    def test_prod_requires_vault(self):
        with pytest.raises(ValueError, match="Vault URL required"):
            InfrastructureConfig(env="PROD", project_root=Path.cwd())

        with pytest.raises(ValueError, match="Vault token or AppRole credentials"):
            InfrastructureConfig(env="PROD", project_root=Path.cwd(), vault_url="https://vault")

        cfg = InfrastructureConfig(
            env="PROD",
            project_root=Path.cwd(),
            vault_url="https://vault",
            vault_token="token",
        )
        assert cfg.vault_token == "token"
