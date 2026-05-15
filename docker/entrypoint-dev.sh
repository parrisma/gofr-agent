#!/bin/bash
set -euo pipefail

# Standard GOFR user paths - all projects use 'gofr' user
GOFR_USER="gofr"
PROJECT_DIR="/home/${GOFR_USER}/devroot/gofr-agent"
# gofr-common is now a git submodule in lib/gofr-common
COMMON_DIR="$PROJECT_DIR/lib/gofr-common"
VENV_DIR="$PROJECT_DIR/.venv"

echo "======================================================================="
echo "GOFR-AGENT Container Entrypoint"
echo "======================================================================="

# -----------------------------------------------------------------------
# Map unknown host GIDs into /etc/group so 'groups' does not warn.
# The container runs with --user UID:GID from the host; those GIDs may
# not exist inside the image.
# -----------------------------------------------------------------------
for _gid in $(id -G 2>/dev/null); do
    if ! getent group "$_gid" >/dev/null 2>&1; then
        sudo groupadd -g "$_gid" "hostgroup_${_gid}" 2>/dev/null || true
    fi
done
unset _gid

ensure_dir() {
    local dir="$1"
    if [ -d "$dir" ]; then
        return 0
    fi
    mkdir -p "$dir" 2>/dev/null || sudo mkdir -p "$dir" 2>/dev/null
}

# -----------------------------------------------------------------------
# Vault AppRole runtime identity (preferred)
# -----------------------------------------------------------------------
# When the shared secrets volume is mounted at /run/gofr-secrets, copy the
# creds file to the standard location expected by gofr-common.
CREDS_SRC="/run/gofr-secrets/service_creds/gofr-agent.json"
CREDS_DST_DIR="/run/secrets"
CREDS_DST="${CREDS_DST_DIR}/vault_creds"

if [ -f "${CREDS_SRC}" ]; then
    echo "Injecting Vault AppRole creds to ${CREDS_DST}"
    sudo mkdir -p "${CREDS_DST_DIR}"
    sudo cp "${CREDS_SRC}" "${CREDS_DST}"
    sudo chmod 600 "${CREDS_DST}"
    sudo chown "$(id -u):$(id -g)" "${CREDS_DST}" || true
else
    echo "Note: Vault AppRole creds not found at ${CREDS_SRC} (dev container may still use GOFR_AGENT_VAULT_TOKEN)"
fi

# Fix data directory permissions if mounted as volume
if [ -d "$PROJECT_DIR/data" ]; then
    if [ ! -w "$PROJECT_DIR/data" ]; then
        echo "Fixing permissions for $PROJECT_DIR/data..."
        sudo chown -R "$(id -u):$(id -g)" "$PROJECT_DIR/data" 2>/dev/null || \
            echo "Warning: Could not fix permissions. Run container with --user $(id -u):$(id -g)"
    fi
fi

# Create subdirectories if they don't exist
if ! ensure_dir "$PROJECT_DIR/data/storage"; then
    echo "Warning: Could not create $PROJECT_DIR/data/storage"
fi
if ! ensure_dir "$PROJECT_DIR/data/auth"; then
    echo "Warning: Could not create $PROJECT_DIR/data/auth"
fi
if ! ensure_dir "$PROJECT_DIR/logs"; then
    echo "Warning: Could not create $PROJECT_DIR/logs (bind mount may be read-only for this UID/GID)"
fi

# Deploy content from app/content/ to data/ (symlinks for instant dev edits)
# In prod images, Dockerfile COPYs real files; in dev we symlink to source.
CONTENT_DIR="$PROJECT_DIR/app/content"
for subdir in templates styles fragments; do
    target="$PROJECT_DIR/data/$subdir"
    source="$CONTENT_DIR/$subdir"
    if [ ! -d "$source" ]; then
        continue
    fi

    # If the data volume already contains these directories/files, don't fail.
    # Prefer a symlink for live-editing, but leave real directories in place.
    if [ -L "$target" ]; then
        existing_link="$(readlink "$target" || true)"
        if [ "$existing_link" != "$source" ]; then
            rm -f "$target" 2>/dev/null || true
            ln -s "$source" "$target"
            echo "Re-linked data/$subdir -> app/content/$subdir"
        fi
        continue
    fi

    if [ -e "$target" ]; then
        echo "Note: data/$subdir already exists (not a symlink); leaving as-is"
        continue
    fi

    ln -s "$source" "$target"
    echo "Linked data/$subdir -> app/content/$subdir"
done

# Ensure virtual environment exists and is valid
if [ ! -f "$VENV_DIR/bin/python" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating Python virtual environment..."
    cd "$PROJECT_DIR"
    UV_VENV_CLEAR=1 uv venv "$VENV_DIR" --python=python3.11
    echo "Virtual environment created at $VENV_DIR"
fi

# Install gofr-common as editable package
if [ -d "$COMMON_DIR" ]; then
    echo "Installing gofr-common (editable)..."
    cd "$PROJECT_DIR"
    uv pip install -e "$COMMON_DIR"
else
    echo "Warning: gofr-common not found at $COMMON_DIR"
    echo "Make sure the submodule is initialized: git submodule update --init"
fi

# Install project dependencies
if [ -f "$PROJECT_DIR/pyproject.toml" ]; then
    echo "Installing project dependencies from pyproject.toml..."
    cd "$PROJECT_DIR"
    uv pip install -e ".[dev]" || echo "Warning: Could not install project dependencies"
elif [ -f "$PROJECT_DIR/requirements.txt" ]; then
    echo "Installing project dependencies from requirements.txt..."
    cd "$PROJECT_DIR"
    uv pip install -r requirements.txt || echo "Warning: Could not install project dependencies"
fi

# Show installed packages
echo ""
echo "Environment ready. Installed packages:"
uv pip list

echo ""
echo "======================================================================="
echo "Entrypoint complete. Executing: $@"
echo "======================================================================="

exec "$@"
