# gofr-common

**Shared Foundation for GOFR Services.**

`gofr-common` provides the reusable building blocks that power the entire GOFR ecosystem (including `gofr-dig`, `gofr-plot`, and others). It ensures that every service handles authentication, logging, and configuration in the exact same reliable way.

## What It Provides

*   **Security**: A unified login and permission system (using JWT and Vault).
*   **Safety**: Automated backup tools for databases and critical files.
*   **Consistency**: Standardized ways to handle settings, logs, and network ports.
*   **Reliability**: Common error handling and web server protections.

## Documentation Map

*   **[Platform Bootstrap](docs/bootstrap.md)**: How to set up the shared core infrastructure (Vault, Docker networks).
*   **[Authentication](docs/auth/gofr_auth_system.md)**: How the secure login system works.
*   **[Backup System](docs/backup/backup.md)**: How data is protected and restored.
*   **[Port Standards](docs/config/port_standardization.md)**: Which network ports are used by which service.
*   **[Developer Standards](docs/technical/gofr_development_standards.md)**: Rules for writing code in this ecosystem.

## Usage

This library is usually installed automatically as a dependency in other GOFR projects.

To install it manually for development:

```bash
uv pip install -e path/to/gofr-common
```
