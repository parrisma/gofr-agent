"""Backup housekeeping and retention management

Handles cleanup of old backups based on age and count policies.
Supports tiered retention (daily, weekly, monthly).
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class BackupInfo:
    """Information about a backup file"""
    filename: str
    filepath: Path
    tier: str  # daily, weekly, monthly
    timestamp: datetime
    size_bytes: int
    verified: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['filepath'] = str(self.filepath)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'BackupInfo':
        """Create from dictionary"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        data['filepath'] = Path(data['filepath'])
        return cls(**data)


class BackupHousekeeping:
    """Manages backup retention and cleanup"""

    def __init__(self, backup_dir: Path, manifest_file: str = "manifest.json"):
        self.backup_dir = Path(backup_dir)
        self.manifest_path = self.backup_dir / manifest_file
        self.logger = logging.getLogger(__name__)

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Create tier directories
        for tier in ['daily', 'weekly', 'monthly']:
            (self.backup_dir / tier).mkdir(exist_ok=True)

    def load_manifest(self) -> Dict[str, BackupInfo]:
        """Load backup manifest from JSON"""
        if not self.manifest_path.exists():
            return {}

        try:
            with open(self.manifest_path, 'r') as f:
                data = json.load(f)

            manifest = {}
            for filename, info in data.items():
                manifest[filename] = BackupInfo.from_dict(info)

            return manifest
        except Exception as e:
            self.logger.error(f"Failed to load manifest: {e}")
            return {}

    def save_manifest(self, manifest: Dict[str, BackupInfo]) -> None:
        """Save backup manifest to JSON"""
        try:
            data = {filename: info.to_dict() for filename, info in manifest.items()}
            with open(self.manifest_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save manifest: {e}")

    def add_backup(self, backup_info: BackupInfo) -> None:
        """Add a backup to the manifest"""
        manifest = self.load_manifest()
        manifest[backup_info.filename] = backup_info
        self.save_manifest(manifest)
        self.logger.info(f"Added backup to manifest: {backup_info.filename}")

    def scan_backups(self, tier: Optional[str] = None) -> List[BackupInfo]:
        """Scan backup directory and return list of backups"""
        backups = []
        manifest = self.load_manifest()

        # Determine which directories to scan
        if tier:
            scan_dirs = [self.backup_dir / tier]
        else:
            scan_dirs = [
                self.backup_dir / 'daily',
                self.backup_dir / 'weekly',
                self.backup_dir / 'monthly'
            ]

        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue

            for backup_file in scan_dir.glob('*.tar*'):
                # Check if in manifest
                if backup_file.name in manifest:
                    backups.append(manifest[backup_file.name])
                else:
                    # Create entry for untracked backup
                    tier_name = backup_file.parent.name
                    backup_info = BackupInfo(
                        filename=backup_file.name,
                        filepath=backup_file,
                        tier=tier_name,
                        timestamp=datetime.fromtimestamp(backup_file.stat().st_mtime),
                        size_bytes=backup_file.stat().st_size,
                        verified=False
                    )
                    backups.append(backup_info)

        return sorted(backups, key=lambda x: x.timestamp, reverse=True)

    def cleanup_by_age(self, retention_days: int, tier: str = 'daily') -> int:
        """Remove backups older than retention_days"""
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        backups = self.scan_backups(tier=tier)
        manifest = self.load_manifest()

        removed_count = 0
        for backup in backups:
            if backup.timestamp < cutoff_date:
                try:
                    backup.filepath.unlink()
                    if backup.filename in manifest:
                        del manifest[backup.filename]
                    removed_count += 1
                    self.logger.info(f"Removed old backup: {backup.filename} (age: {(datetime.now() - backup.timestamp).days} days)")
                except Exception as e:
                    self.logger.error(f"Failed to remove {backup.filename}: {e}")

        if removed_count > 0:
            self.save_manifest(manifest)

        return removed_count

    def cleanup_by_count(self, max_count: int, tier: str = 'daily') -> int:
        """Keep only the most recent max_count backups"""
        backups = self.scan_backups(tier=tier)

        if len(backups) <= max_count:
            return 0

        manifest = self.load_manifest()
        backups_to_remove = backups[max_count:]
        removed_count = 0

        for backup in backups_to_remove:
            try:
                backup.filepath.unlink()
                if backup.filename in manifest:
                    del manifest[backup.filename]
                removed_count += 1
                self.logger.info(f"Removed excess backup: {backup.filename}")
            except Exception as e:
                self.logger.error(f"Failed to remove {backup.filename}: {e}")

        if removed_count > 0:
            self.save_manifest(manifest)

        return removed_count

    def cleanup_weekly(self, retention_weeks: int) -> int:
        """Cleanup weekly backups older than retention_weeks"""
        retention_days = retention_weeks * 7
        return self.cleanup_by_age(retention_days, tier='weekly')

    def cleanup_monthly(self, retention_months: int) -> int:
        """Cleanup monthly backups older than retention_months"""
        retention_days = retention_months * 30
        return self.cleanup_by_age(retention_days, tier='monthly')

    def run_cleanup(
        self,
        retention_days: int,
        max_count: int,
        weekly_retention_weeks: Optional[int] = None,
        monthly_retention_months: Optional[int] = None
    ) -> Dict[str, int]:
        """Run all cleanup operations"""
        results = {}

        # Daily backups
        results['daily_by_age'] = self.cleanup_by_age(retention_days, tier='daily')
        results['daily_by_count'] = self.cleanup_by_count(max_count, tier='daily')

        # Weekly backups
        if weekly_retention_weeks:
            results['weekly'] = self.cleanup_weekly(weekly_retention_weeks)

        # Monthly backups
        if monthly_retention_months:
            results['monthly'] = self.cleanup_monthly(monthly_retention_months)

        total_removed = sum(results.values())
        self.logger.info(f"Cleanup complete: removed {total_removed} backup(s)")

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get backup statistics"""
        backups = self.scan_backups()

        if not backups:
            return {
                'total_backups': 0,
                'total_size_bytes': 0,
                'total_size_mb': 0,
                'oldest_backup': None,
                'newest_backup': None,
                'by_tier': {}
            }

        total_size = sum(b.size_bytes for b in backups)
        by_tier = {}

        for tier in ['daily', 'weekly', 'monthly']:
            tier_backups = [b for b in backups if b.tier == tier]
            if tier_backups:
                by_tier[tier] = {
                    'count': len(tier_backups),
                    'size_bytes': sum(b.size_bytes for b in tier_backups),
                    'oldest': min(tier_backups, key=lambda x: x.timestamp).timestamp.isoformat(),
                    'newest': max(tier_backups, key=lambda x: x.timestamp).timestamp.isoformat()
                }

        return {
            'total_backups': len(backups),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'oldest_backup': min(backups, key=lambda x: x.timestamp).timestamp.isoformat(),
            'newest_backup': max(backups, key=lambda x: x.timestamp).timestamp.isoformat(),
            'by_tier': by_tier
        }
