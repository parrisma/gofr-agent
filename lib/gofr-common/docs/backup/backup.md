# Backup System

This system automatically protects data for all GOFR services.

## Key Features

*   **Zero Downtime**: Backups run while the service is live.
*   **Automatic Cleanup**: Old backups are removed after 30 days (configurable).
*   **Integrity Checks**: Every backup is verified with checksums.

## How to Use

Backups typically run as a sidecar container in Docker.

### Manual Operations

You can manage backups manually using scripts in your project's `scripts/` folder:

*   **Run Backup Immediately**: `./scripts/backup_now.sh`
*   **See Available Backups**: `./scripts/list_backups.sh`
*   **Restore Data**: `./scripts/restore_backup.sh <filename>`

## Configuration

Backup behavior is controlled by environment variables in `docker-compose.yml`:

*   `GOFR_{PROJECT}_BACKUP_SCHEDULE`: When to run (cron format). Default: 2 AM daily.
*   `GOFR_{PROJECT}_BACKUP_RETENTION_DAYS`: How long to keep files. Default: 30 days.
*   `GOFR_{PROJECT}_BACKUP_PATHS`: Which folders to back up.
