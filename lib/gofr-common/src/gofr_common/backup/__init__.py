"""GOFR Common Backup Module

Shared backup infrastructure for all GOFR projects.

Usage:
    from gofr_common.backup import BackupService, BackupConfig

    # For gofr-plot
    config = BackupConfig.from_env(project_name="plot")
    service = BackupService(config)
    service.start()
"""

from gofr_common.backup.config import BackupConfig
from gofr_common.backup.housekeeping import BackupHousekeeping, BackupInfo
from gofr_common.backup.service import BackupService
from gofr_common.backup.verify import BackupVerifier

__all__ = [
    "BackupConfig",
    "BackupService",
    "BackupHousekeeping",
    "BackupInfo",
    "BackupVerifier",
]
