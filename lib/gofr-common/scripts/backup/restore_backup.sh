#!/bin/bash
#
# restore_backup.sh - Restore from a backup archive (Shared GOFR script)
#
# Usage:
#   GOFR_PROJECT=plot ./restore_backup.sh <backup_filename>
#   GOFR_PROJECT=plot ./restore_backup.sh --interactive
#   GOFR_PROJECT=plot ./restore_backup.sh --latest
#

set -e

# Require GOFR_PROJECT
if [ -z "$GOFR_PROJECT" ]; then
    echo "ERROR: GOFR_PROJECT environment variable not set"
    echo "Usage: GOFR_PROJECT=plot ./restore_backup.sh [options]"
    echo "Projects: plot, doc, iq, np, dig"
    exit 1
fi

CONTAINER_NAME="${GOFR_BACKUP_CONTAINER:-gofr-${GOFR_PROJECT}-backup}"
BACKUP_FILENAME="$1"
DATA_VOLUME="${GOFR_DATA_VOLUME:-gofr-${GOFR_PROJECT}_data}"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=== GOFR-${GOFR_PROJECT} Backup Restoration ==="
echo

# Check if backup container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}ERROR: Backup container '${CONTAINER_NAME}' is not running${NC}"
    echo "Start the backup service first: docker-compose up -d backup"
    exit 1
fi

# Interactive mode - list and select backup
if [ "$BACKUP_FILENAME" == "--interactive" ]; then
    echo "Available backups:"
    echo
    
    # Get list of backups
    BACKUPS=$(docker exec "${CONTAINER_NAME}" find /backups -name "*.tar*" -type f ! -name "*.sha256" -printf "%f\n" | sort -r)
    
    if [ -z "$BACKUPS" ]; then
        echo -e "${RED}No backups found${NC}"
        exit 1
    fi
    
    # Display numbered list
    IFS=$'\n' read -rd '' -a BACKUP_ARRAY <<<"$BACKUPS" || true
    for i in "${!BACKUP_ARRAY[@]}"; do
        echo "  $((i+1)). ${BACKUP_ARRAY[$i]}"
    done
    
    echo
    read -p "Select backup number (or 'q' to quit): " selection
    
    if [ "$selection" == "q" ] || [ "$selection" == "Q" ]; then
        echo "Cancelled"
        exit 0
    fi
    
    # Validate selection
    if ! [[ "$selection" =~ ^[0-9]+$ ]] || [ "$selection" -lt 1 ] || [ "$selection" -gt "${#BACKUP_ARRAY[@]}" ]; then
        echo -e "${RED}Invalid selection${NC}"
        exit 1
    fi
    
    BACKUP_FILENAME="${BACKUP_ARRAY[$((selection-1))]}"
fi

# Latest backup mode
if [ "$BACKUP_FILENAME" == "--latest" ]; then
    echo "Finding latest backup..."
    BACKUP_FILENAME=$(docker exec "${CONTAINER_NAME}" find /backups -name "*.tar*" -type f ! -name "*.sha256" -printf "%T@ %f\n" | sort -rn | head -1 | cut -d' ' -f2)
    
    if [ -z "$BACKUP_FILENAME" ]; then
        echo -e "${RED}No backups found${NC}"
        exit 1
    fi
    
    echo "Latest backup: ${BACKUP_FILENAME}"
fi

# Validate backup filename provided
if [ -z "$BACKUP_FILENAME" ]; then
    echo "Usage: GOFR_PROJECT=${GOFR_PROJECT} $0 <backup_filename>"
    echo "       GOFR_PROJECT=${GOFR_PROJECT} $0 --interactive"
    echo "       GOFR_PROJECT=${GOFR_PROJECT} $0 --latest"
    echo
    echo "Use GOFR_PROJECT=${GOFR_PROJECT} ./list_backups.sh to see available backups"
    exit 1
fi

# Find backup file in any tier directory
BACKUP_PATH=$(docker exec "${CONTAINER_NAME}" find /backups -name "${BACKUP_FILENAME}" -type f ! -name "*.sha256" | head -1)

if [ -z "$BACKUP_PATH" ]; then
    echo -e "${RED}ERROR: Backup file '${BACKUP_FILENAME}' not found${NC}"
    echo "Use GOFR_PROJECT=${GOFR_PROJECT} ./list_backups.sh to see available backups"
    exit 1
fi

echo "Selected backup: ${BACKUP_FILENAME}"
echo "Backup path: ${BACKUP_PATH}"
echo

# Warning and confirmation
echo -e "${YELLOW}WARNING: This will restore data from the backup archive.${NC}"
echo -e "${YELLOW}Current data in ${DATA_VOLUME} will be OVERWRITTEN.${NC}"
echo
echo "It is recommended to:"
echo "  1. Stop gofr-${GOFR_PROJECT} services: docker-compose stop mcp mcpo web"
echo "  2. Create a current backup before restoring"
echo
read -p "Do you want to proceed? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Restoration cancelled"
    exit 0
fi

echo
echo "Starting restoration..."

# Verify backup before restoring
echo "Verifying backup integrity..."
docker exec "${CONTAINER_NAME}" python3 -c "
from gofr_common.backup.verify import BackupVerifier
from pathlib import Path
import sys

verifier = BackupVerifier()
success, results = verifier.verify_backup(Path('${BACKUP_PATH}'))

if not success:
    print('ERROR: Backup verification failed')
    print(results)
    sys.exit(1)

print('✓ Backup verification passed')
" || {
    echo -e "${RED}Backup verification failed. Aborting restoration.${NC}"
    exit 1
}

echo

# Extract backup to a temporary location and then copy to data volume
echo "Extracting backup..."
docker exec "${CONTAINER_NAME}" sh -c "
    # Create temporary extraction directory
    TEMP_DIR=/tmp/restore_$$
    mkdir -p \${TEMP_DIR}
    
    # Extract backup
    tar -xf '${BACKUP_PATH}' -C \${TEMP_DIR}
    
    # Copy extracted data to /data
    if [ -d \${TEMP_DIR}/data ]; then
        cp -rf \${TEMP_DIR}/data/* /data/
    else
        # Backup might have different structure
        cp -rf \${TEMP_DIR}/* /data/
    fi
    
    # Cleanup
    rm -rf \${TEMP_DIR}
    
    echo 'Extraction complete'
"

if [ $? -eq 0 ]; then
    echo
    echo -e "${GREEN}✓ Restoration completed successfully${NC}"
    echo
    echo "Next steps:"
    echo "  1. Restart gofr-${GOFR_PROJECT} services: docker-compose restart mcp mcpo web"
    echo "  2. Verify service functionality"
else
    echo
    echo -e "${RED}✗ Restoration failed${NC}"
    exit 1
fi
