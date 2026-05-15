#!/bin/bash
#
# list_backups.sh - List all available backups (Shared GOFR script)
#
# Usage:
#   GOFR_PROJECT=plot ./list_backups.sh
#

set -e

# Require GOFR_PROJECT
if [ -z "$GOFR_PROJECT" ]; then
    echo "ERROR: GOFR_PROJECT environment variable not set"
    echo "Usage: GOFR_PROJECT=plot ./list_backups.sh"
    echo "Projects: plot, doc, iq, np, dig"
    exit 1
fi

CONTAINER_NAME="${GOFR_BACKUP_CONTAINER:-gofr-${GOFR_PROJECT}-backup}"

echo "=== GOFR-${GOFR_PROJECT} Backup Inventory ==="
echo

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Backup container '${CONTAINER_NAME}' is not running"
    echo "Start the backup service first: docker-compose up -d backup"
    exit 1
fi

# List backups
docker exec "${CONTAINER_NAME}" python3 -c "
from gofr_common.backup.config import BackupConfig
from gofr_common.backup.housekeeping import BackupHousekeeping
from datetime import datetime
import os

project_name = os.getenv('GOFR_PROJECT', '${GOFR_PROJECT}')
config = BackupConfig.from_env(project_name=project_name)
housekeeping = BackupHousekeeping(config.backup_dir)

# Get all backups
backups = housekeeping.scan_backups()

if not backups:
    print('No backups found')
else:
    print(f'Found {len(backups)} backup(s):\n')
    
    # Group by tier
    for tier in ['daily', 'weekly', 'monthly']:
        tier_backups = [b for b in backups if b.tier == tier]
        if not tier_backups:
            continue
        
        print(f'{tier.upper()} BACKUPS ({len(tier_backups)}):')
        print('-' * 80)
        
        for backup in sorted(tier_backups, key=lambda x: x.timestamp, reverse=True):
            age_days = (datetime.now() - backup.timestamp).days
            size_mb = backup.size_bytes / (1024 * 1024)
            verified = '✓' if backup.verified else '✗'
            
            print(f'  {backup.filename}')
            print(f'    Size: {size_mb:.2f} MB | Age: {age_days} days | Verified: {verified}')
            print(f'    Created: {backup.timestamp.strftime(\"%Y-%m-%d %H:%M:%S\")}')
            print()
        
        print()
    
    # Show statistics
    stats = housekeeping.get_stats()
    print('SUMMARY:')
    print('-' * 80)
    print(f'Total Backups: {stats[\"total_backups\"]}')
    print(f'Total Size: {stats[\"total_size_mb\"]} MB')
    if stats['oldest_backup']:
        print(f'Oldest: {stats[\"oldest_backup\"]}')
    if stats['newest_backup']:
        print(f'Newest: {stats[\"newest_backup\"]}')
"

echo
echo "To create an immediate backup, run: GOFR_PROJECT=${GOFR_PROJECT} ./backup_now.sh"
echo "To restore a backup, run: GOFR_PROJECT=${GOFR_PROJECT} ./restore_backup.sh <backup_filename>"
