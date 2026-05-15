#!/usr/bin/env python3
"""Backup Service Orchestrator for GOFR projects

Parameterized backup service that works with any GOFR project.
Coordinates scheduled backups, verification, and housekeeping.
"""

import logging
import signal
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from gofr_common.backup.config import BackupConfig
from gofr_common.backup.housekeeping import BackupHousekeeping, BackupInfo
from gofr_common.backup.verify import BackupVerifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class BackupService:
    """Main backup service orchestrator for GOFR projects"""

    def __init__(self, config: BackupConfig):
        self.config = config
        self.housekeeping = BackupHousekeeping(config.backup_dir)
        self.verifier = BackupVerifier()
        self.scheduler = BlockingScheduler()
        self.shutdown_requested = False

        logger.info(f"Backup service initialized for gofr-{config.project_name}")
        logger.info(f"Data directory: {config.data_dir}")
        logger.info(f"Backup directory: {config.backup_dir}")
        logger.info(f"Schedule: {config.schedule}")
        logger.info(f"Retention: {config.retention_days} days, max {config.max_count} backups")

    def create_backup(self, tier: str = 'daily') -> Optional[Path]:
        """Create a backup archive

        Args:
            tier: Backup tier (daily, weekly, monthly)

        Returns:
            Path to created backup file, or None if failed
        """
        logger.info(f"Starting {tier} backup...")

        # Generate backup filename
        filename = self.config.generate_backup_filename(tier)
        backup_path = self.config.backup_dir / tier / filename

        # Ensure tier directory exists
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        # Get paths to backup
        paths_to_backup = self.config.get_backup_paths()

        if not paths_to_backup:
            logger.warning("No data found to backup")
            return None

        logger.info(f"Backing up {len(paths_to_backup)} paths: {[name for name, _ in paths_to_backup]}")

        try:
            # Create tar archive
            compression_flag = self.config.get_compression_flag()
            mode = f'w:{compression_flag}' if compression_flag else 'w'

            with tarfile.open(backup_path, mode) as tar:  # type: ignore[call-overload]
                for name, path in paths_to_backup:
                    if path.exists():
                        # Add with arcname to preserve structure
                        arcname = path.relative_to(self.config.data_dir.parent) if path.is_relative_to(self.config.data_dir.parent) else path.name
                        tar.add(path, arcname=arcname)
                        logger.debug(f"Added {name}: {path}")

            # Get file size
            size_bytes = backup_path.stat().st_size
            size_mb = size_bytes / (1024 * 1024)
            logger.info(f"Backup created: {filename} ({size_mb:.2f} MB)")

            # Calculate and save checksum
            checksum = self.verifier.calculate_checksum(backup_path)
            self.verifier.save_checksum(backup_path, checksum)

            # Add to manifest
            backup_info = BackupInfo(
                filename=filename,
                filepath=backup_path,
                tier=tier,
                timestamp=datetime.now(),
                size_bytes=size_bytes,
                verified=False
            )
            self.housekeeping.add_backup(backup_info)

            return backup_path

        except Exception as e:
            logger.error(f"Backup creation failed: {e}", exc_info=True)
            # Cleanup failed backup
            if backup_path.exists():
                backup_path.unlink()
            return None

    def verify_backup(self, backup_path: Path) -> bool:
        """Verify a backup file

        Args:
            backup_path: Path to backup file

        Returns:
            True if verification passed
        """
        logger.info(f"Verifying backup: {backup_path.name}")

        try:
            success, results = self.verifier.verify_backup(backup_path)

            if success:
                logger.info(f"Backup verification passed: {backup_path.name}")
                # Update manifest
                manifest = self.housekeeping.load_manifest()
                if backup_path.name in manifest:
                    manifest[backup_path.name].verified = True
                    self.housekeeping.save_manifest(manifest)
            else:
                logger.error(f"Backup verification failed: {results.get('errors', [])}")

            return success

        except Exception as e:
            logger.error(f"Backup verification error: {e}", exc_info=True)
            return False

    def run_backup_job(self):
        """Run scheduled backup job"""
        if self.shutdown_requested:
            logger.info("Shutdown requested, skipping backup")
            return

        logger.info("=== Backup job started ===")

        # Create backup
        backup_path = self.create_backup(tier='daily')

        if backup_path:
            # Verify if configured
            if self.config.verify_after_backup:
                self.verify_backup(backup_path)

            # Run housekeeping
            logger.info("Running housekeeping...")
            cleanup_results = self.housekeeping.run_cleanup(
                retention_days=self.config.retention_days,
                max_count=self.config.max_count,
                weekly_retention_weeks=self.config.weekly_retention_weeks if self.config.enable_weekly else None,
                monthly_retention_months=self.config.monthly_retention_months if self.config.enable_monthly else None
            )
            logger.info(f"Housekeeping results: {cleanup_results}")

            # Log statistics
            stats = self.housekeeping.get_stats()
            logger.info(f"Backup statistics: {stats['total_backups']} backups, {stats['total_size_mb']} MB total")

        logger.info("=== Backup job completed ===")

    def run_initial_cleanup(self):
        """Run initial cleanup on service start"""
        if not self.config.cleanup_on_start:
            logger.info("Initial cleanup disabled")
            return

        logger.info("Running initial cleanup...")
        cleanup_results = self.housekeeping.run_cleanup(
            retention_days=self.config.retention_days,
            max_count=self.config.max_count,
            weekly_retention_weeks=self.config.weekly_retention_weeks if self.config.enable_weekly else None,
            monthly_retention_months=self.config.monthly_retention_months if self.config.enable_monthly else None
        )
        logger.info(f"Initial cleanup results: {cleanup_results}")

    def setup_scheduler(self):
        """Setup backup scheduler"""
        if not self.config.enabled:
            logger.warning("Backup service is DISABLED")
            return

        # Parse cron schedule
        try:
            minute, hour, day, month, day_of_week = self.config.schedule.split()

            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week
            )

            self.scheduler.add_job(
                self.run_backup_job,
                trigger=trigger,
                id='backup_job',
                name='Scheduled Backup',
                misfire_grace_time=3600  # Allow 1 hour grace period
            )

            logger.info(f"Backup scheduled: {self.config.schedule}")

            # Log next run time
            jobs = self.scheduler.get_jobs()
            if jobs:
                next_run = jobs[0].next_run_time
                logger.info(f"Next backup scheduled for: {next_run}")

        except Exception as e:
            logger.error(f"Failed to setup scheduler: {e}")
            raise

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True
        self.scheduler.shutdown(wait=False)
        sys.exit(0)

    def start(self):
        """Start the backup service"""
        logger.info("=" * 60)
        logger.info(f"GOFR-{self.config.project_name.upper()} Backup Service Starting")
        logger.info("=" * 60)

        # Register signal handlers
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)

        # Run initial cleanup
        self.run_initial_cleanup()

        # Display current stats
        stats = self.housekeeping.get_stats()
        logger.info(f"Current backup statistics: {stats}")

        if not self.config.enabled:
            logger.warning("Backup service is DISABLED - entering idle mode")
            logger.info(f"Set {self.config.env_prefix}_ENABLED=true to enable backups")
            # Keep service running but idle
            signal.pause()
            return

        # Setup and start scheduler
        self.setup_scheduler()

        logger.info("Backup service started successfully")
        logger.info("Press Ctrl+C to stop")

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Backup service stopped")


def main():
    """Main entry point - requires GOFR_PROJECT environment variable"""
    try:
        # Get project name from environment
        project_name = os.getenv("GOFR_PROJECT", "").lower()

        if not project_name:
            logger.error("GOFR_PROJECT environment variable not set")
            logger.error("Set GOFR_PROJECT to one of: plot, doc, iq, np, dig")
            sys.exit(1)

        # Load configuration for the project
        config = BackupConfig.from_env(project_name=project_name)

        # Create and start service
        service = BackupService(config)
        service.start()

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    import os
    main()
