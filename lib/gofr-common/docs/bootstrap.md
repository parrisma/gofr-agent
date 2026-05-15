# Platform Setup

This guide explains how to set up the shared infrastructure required by all GOFR services.

Most users should just run the automated script.

## Quick Start

We provide a single script to handle all platform setup.

**Interactive Mode (Recommended)**:

```bash
./lib/gofr-common/scripts/bootstrap_platform.sh
```

**Automated Mode**:

```bash
./lib/gofr-common/scripts/bootstrap_platform.sh --yes
```

## What This Does

The script automatically performs the following steps:

1.  **Base Image**: Builds the shared `gofr-base` Docker image.
2.  **Vault Service**: Builds and starts the Vault security container.
3.  **Networking**: Creates the `gofr-net` and `gofr-test-net` Docker networks.
4.  **Security Bootstrap**: 
    *   Initializes Vault.
    *   Generates encryption keys.
    *   Creates a secure signing secret for logins.
5.  **Data Seeding**: Copies the generated keys into Docker volumes so services can use them.

## Common Tasks

### Unsealing Vault

If your computer restarts, Vault will lock itself (seal) for security. To unlock it:

```bash
cd lib/gofr-common
./scripts/manage_vault.sh start
./scripts/manage_vault.sh unseal
```

### Checking Health

To verify that the platform services are running correctly:

```bash
cd lib/gofr-common
./scripts/manage_vault.sh health
```

## Manual Setup (Reference)

If you cannot use the script, these are the individual commands required:

1.  **Initialize Submodules**: `git submodule update --init --recursive`
2.  **Build Base**: `docker build -f docker/Dockerfile.base -t gofr-base:latest .` (in `lib/gofr-common`)
3.  **Build Vault**: `./docker/build-vault.sh`
4.  **Create Networks**: `docker network create gofr-net`
5.  **Bootstrap Vault**: `cd lib/gofr-common && ./scripts/manage_vault.sh bootstrap`
6.  **Seed Volumes**: `./scripts/migrate_secrets_to_volume.sh`
