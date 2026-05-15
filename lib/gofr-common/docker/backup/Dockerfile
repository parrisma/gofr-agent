FROM python:3.11-slim

# Install system dependencies for backup operations
RUN apt-get update && apt-get install -y \
    tar \
    gzip \
    bzip2 \
    xz-utils \
    rsync \
    && rm -rf /var/lib/apt/lists/*

# Add Unix group 'gofr-backup' with auto-allocated GID
RUN groupadd --system gofr-backup

# Add user 'gofr-backup' with auto-allocated UID
RUN useradd --system --gid gofr-backup --home-dir /home/gofr-backup --create-home gofr-backup

# Create backup directories
RUN mkdir -p /backups \
    && chown -R gofr-backup:gofr-backup /home/gofr-backup /backups

# Switch to gofr-backup user
USER gofr-backup
WORKDIR /home/gofr-backup

# Create virtual environment
RUN python -m venv /home/gofr-backup/.venv

# Set environment to use the venv
ENV VIRTUAL_ENV=/home/gofr-backup/.venv
ENV PATH="/home/gofr-backup/.venv/bin:$PATH"

# Install gofr-common with backup dependencies
# First copy just the requirements
COPY --chown=gofr-backup:gofr-backup pyproject.toml /tmp/gofr-common/
COPY --chown=gofr-backup:gofr-backup src/ /tmp/gofr-common/src/
COPY --chown=gofr-backup:gofr-common readme.md /tmp/gofr-common/

# Install gofr-common
RUN pip install --no-cache-dir /tmp/gofr-common \
    && pip install --no-cache-dir \
        apscheduler==3.10.4 \
    && rm -rf /tmp/gofr-common

# Copy entrypoint script
COPY --chown=gofr-backup:gofr-backup docker/backup/entrypoint.sh /home/gofr-backup/

RUN chmod +x /home/gofr-backup/entrypoint.sh

# Default entrypoint
ENTRYPOINT ["/home/gofr-backup/entrypoint.sh"]
