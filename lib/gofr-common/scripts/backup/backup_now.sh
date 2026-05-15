#!/bin/bash
#
# backup_now.sh - Trigger an immediate backup (Shared GOFR script)
#
# Usage:
#   GOFR_PROJECT=plot ./backup_now.sh
#   GOFR_PROJECT=doc ./backup_now.sh daily
#

set -e

# Require GOFR_PROJECT
if [ -z "$GOFR_PROJECT" ]; then
    echo "ERROR: GOFR_PROJECT environment variable not set"
    echo "Usage: GOFR_PROJECT=plot ./backup_now.sh [tier]"
    echo "Projects: plot, doc, iq, np, dig"
    exit 1
fi

CONTAINER_NAME="${GOFR_BACKUP_CONTAINER:-gofr-${GOFR_PROJECT}-backup}"
TIER="${1:-daily}"

echo "=== GOFR-${GOFR_PROJECT} Immediate Backup ==="
echo "Container: ${CONTAINER_NAME}"
echo "Tier: ${TIER}"
echo

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Backup container '${CONTAINER_NAME}' is not running"
    echo "Start the backup service first: docker-compose up -d backup"
    exit 1
fi

# Execute backup inside container
echo "Triggering backup..."
docker exec -it "${CONTAINER_NAME}" python3 -c "
from gofr_common.backup.config import BackupConfig
from gofr_common.backup.service import BackupService
import logging
import sys
import os

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

project_name = os.getenv('GOFR_PROJECT', '${GOFR_PROJECT}')
config = BackupConfig.from_env(project_name=project_name)
service = BackupService(config)

backup_path = service.create_backup(tier='${TIER}')

if backup_path:
    if config.verify_after_backup:
        service.verify_backup(backup_path)
    print(f'Backup created successfully: {backup_path.name}')
    sys.exit(0)
else:
    print('Backup failed')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    echo
    echo "✓ Backup completed successfully"
    echo
    echo "To list all backups, run: GOFR_PROJECT=${GOFR_PROJECT} ./list_backups.sh"
else
    echo
    echo "✗ Backup failed"
    exit 1
fi
