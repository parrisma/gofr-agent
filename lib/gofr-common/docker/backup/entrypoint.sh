#!/bin/bash
set -e

# Entrypoint for GOFR backup service
# Requires GOFR_PROJECT environment variable

if [ -z "$GOFR_PROJECT" ]; then
    echo "ERROR: GOFR_PROJECT environment variable not set"
    echo "Set GOFR_PROJECT to one of: plot, doc, iq, np, dig"
    exit 1
fi

echo "Starting GOFR-${GOFR_PROJECT} backup service..."

# Run the backup service
exec python -m gofr_common.backup.service
