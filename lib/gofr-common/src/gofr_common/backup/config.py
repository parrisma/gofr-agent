"""Backup configuration management for GOFR services

Parameterized backup configuration that works across all GOFR projects.
Supports environment variable overrides with project-specific prefixes.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class BackupConfig(BaseModel):
    """Backup service configuration with environment variable overrides

    Parameterized to work with any GOFR project by specifying an env_prefix.
    """

    # Project identification
    project_name: str = Field(
        default="gofr",
        description="Project name (e.g., 'plot', 'doc', 'iq')"
    )
    env_prefix: str = Field(
        default="GOFR",
        description="Environment variable prefix (e.g., 'GOFR_PLOT')"
    )

    # Backup scheduling
    enabled: bool = Field(
        default=True,
        description="Enable/disable backup service"
    )
    schedule: str = Field(
        default="0 2 * * *",
        description="Backup schedule in cron format (default: 2 AM daily)"
    )

    # Retention policies
    retention_days: int = Field(
        default=30,
        description="Days to keep backups (age-based retention)",
        ge=1
    )
    max_count: int = Field(
        default=90,
        description="Maximum number of backups to keep (count-based retention)",
        ge=1
    )

    # What to backup - customizable per project
    backup_paths: List[tuple[str, str]] = Field(
        default_factory=list,
        description="List of (name, relative_path) tuples to backup"
    )

    # Compression settings
    compression: str = Field(
        default="gzip",
        description="Compression algorithm: gzip, bzip2, xz, or none"
    )
    compression_level: int = Field(
        default=6,
        description="Compression level (1-9, higher = better compression but slower)",
        ge=1,
        le=9
    )

    # Housekeeping
    cleanup_on_start: bool = Field(
        default=True,
        description="Run cleanup on service startup"
    )
    verify_after_backup: bool = Field(
        default=True,
        description="Verify backup integrity after creation"
    )

    # Naming and paths
    backup_prefix: str = Field(
        default="gofr",
        description="Prefix for backup filenames"
    )
    timestamp_format: str = Field(
        default="%Y%m%d_%H%M%S",
        description="Timestamp format for backup filenames"
    )

    # Directories
    data_dir: Path = Field(
        default=Path("/data"),
        description="Source data directory (read-only mount)"
    )
    backup_dir: Path = Field(
        default=Path("/backups"),
        description="Backup destination directory"
    )

    # Tiered retention (optional)
    enable_weekly: bool = Field(
        default=False,
        description="Enable weekly backup tier"
    )
    enable_monthly: bool = Field(
        default=False,
        description="Enable monthly backup tier"
    )
    weekly_retention_weeks: int = Field(
        default=8,
        description="Weeks to keep weekly backups",
        ge=1
    )
    monthly_retention_months: int = Field(
        default=12,
        description="Months to keep monthly backups",
        ge=1
    )

    @field_validator('compression')
    @classmethod
    def validate_compression(cls, v: str) -> str:
        """Validate compression algorithm"""
        valid = ['gzip', 'bzip2', 'xz', 'none']
        if v.lower() not in valid:
            raise ValueError(f"Compression must be one of: {', '.join(valid)}")
        return v.lower()

    @field_validator('schedule')
    @classmethod
    def validate_schedule(cls, v: str) -> str:
        """Validate cron schedule format (basic check)"""
        parts = v.split()
        if len(parts) != 5:
            raise ValueError("Schedule must be in cron format: 'minute hour day month weekday'")
        return v

    def get_compression_extension(self) -> str:
        """Get file extension for current compression setting"""
        extensions = {
            'gzip': '.tar.gz',
            'bzip2': '.tar.bz2',
            'xz': '.tar.xz',
            'none': '.tar'
        }
        return extensions.get(self.compression, '.tar.gz')

    def get_compression_flag(self) -> str:
        """Get tar compression flag"""
        flags = {
            'gzip': 'z',
            'bzip2': 'j',
            'xz': 'J',
            'none': ''
        }
        return flags.get(self.compression, 'z')

    def generate_backup_filename(self, tier: str = "daily") -> str:
        """Generate backup filename with timestamp"""
        timestamp = datetime.now().strftime(self.timestamp_format)
        ext = self.get_compression_extension()
        return f"{self.backup_prefix}_{tier}_{timestamp}{ext}"

    def get_backup_paths(self) -> List[tuple[str, Path]]:
        """Get list of paths to backup based on configuration

        Returns paths that actually exist on the filesystem.
        """
        paths = []

        for name, relative_path in self.backup_paths:
            # Support both absolute and relative paths
            if relative_path.startswith('/'):
                full_path = Path(relative_path)
            else:
                full_path = self.data_dir / relative_path

            if full_path.exists():
                paths.append((name, full_path))

        return paths

    @classmethod
    def from_env(
        cls,
        project_name: str = "gofr",
        env_prefix: Optional[str] = None,
        default_backup_paths: Optional[List[tuple[str, str]]] = None
    ) -> "BackupConfig":
        """Create configuration from environment variables

        Args:
            project_name: Name of the GOFR project (e.g., 'plot', 'doc', 'iq')
            env_prefix: Override environment variable prefix (default: GOFR_{PROJECT}_BACKUP)
            default_backup_paths: Default paths to backup if not specified in env

        Returns:
            BackupConfig instance
        """
        if env_prefix is None:
            env_prefix = f"GOFR_{project_name.upper()}_BACKUP"
        else:
            env_prefix = env_prefix.rstrip('_')

        # Default backup paths if not provided
        if default_backup_paths is None:
            default_backup_paths = [
                ("storage", "storage"),
                ("auth", "auth"),
                ("logs", "../logs"),
            ]

        # Parse backup paths from environment (comma-separated name:path pairs)
        # Format: GOFR_PLOT_BACKUP_PATHS="storage:storage,auth:auth,logs:../logs"
        backup_paths_env = os.getenv(f"{env_prefix}_PATHS", "")
        if backup_paths_env:
            backup_paths = []
            for pair in backup_paths_env.split(','):
                if ':' in pair:
                    name, path = pair.split(':', 1)
                    backup_paths.append((name.strip(), path.strip()))
        else:
            backup_paths = default_backup_paths

        return cls(
            project_name=project_name,
            env_prefix=env_prefix,
            enabled=os.getenv(f"{env_prefix}_ENABLED", "true").lower() == "true",
            schedule=os.getenv(f"{env_prefix}_SCHEDULE", "0 2 * * *"),
            retention_days=int(os.getenv(f"{env_prefix}_RETENTION_DAYS", "30")),
            max_count=int(os.getenv(f"{env_prefix}_MAX_COUNT", "90")),
            backup_paths=backup_paths,
            compression=os.getenv(f"{env_prefix}_COMPRESSION", "gzip"),
            compression_level=int(os.getenv(f"{env_prefix}_COMPRESSION_LEVEL", "6")),
            cleanup_on_start=os.getenv(f"{env_prefix}_CLEANUP_ON_START", "true").lower() == "true",
            verify_after_backup=os.getenv(f"{env_prefix}_VERIFY_AFTER_BACKUP", "true").lower() == "true",
            backup_prefix=os.getenv(f"{env_prefix}_PREFIX", f"gofr-{project_name}"),
            timestamp_format=os.getenv(f"{env_prefix}_FORMAT", "%Y%m%d_%H%M%S"),
            data_dir=Path(os.getenv(f"{env_prefix}_DATA_DIR", "/data")),
            backup_dir=Path(os.getenv(f"{env_prefix}_BACKUP_DIR", "/backups")),
            enable_weekly=os.getenv(f"{env_prefix}_ENABLE_WEEKLY", "false").lower() == "true",
            enable_monthly=os.getenv(f"{env_prefix}_ENABLE_MONTHLY", "false").lower() == "true",
            weekly_retention_weeks=int(os.getenv(f"{env_prefix}_WEEKLY_RETENTION_WEEKS", "8")),
            monthly_retention_months=int(os.getenv(f"{env_prefix}_MONTHLY_RETENTION_MONTHS", "12")),
        )


# Project-specific helper functions
def get_plot_backup_config() -> BackupConfig:
    """Get backup configuration for gofr-plot"""
    return BackupConfig.from_env(
        project_name="plot",
        default_backup_paths=[
            ("storage", "storage"),
            ("auth", "auth"),
            ("logs", "../logs"),
        ]
    )


def get_doc_backup_config() -> BackupConfig:
    """Get backup configuration for gofr-doc"""
    return BackupConfig.from_env(
        project_name="doc",
        default_backup_paths=[
            ("storage", "storage"),
            ("auth", "auth"),
            ("logs", "../logs"),
        ]
    )


def get_iq_backup_config() -> BackupConfig:
    """Get backup configuration for gofr-iq"""
    return BackupConfig.from_env(
        project_name="iq",
        default_backup_paths=[
            ("data", "."),  # All data directory
            ("logs", "../logs"),
        ]
    )
