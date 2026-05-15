# Developer Standards

This is a cheat sheet for writing code in the GOFR ecosystem.

## 1. Where We Code

*   **Containers Only**: We develop inside Docker containers (Dev Containers).
*   **No Local Env**: Don't manage Python environments on your host machine.

## 2. Using gofr-common

The `gofr-common` library is the backbone of everything.

*   **Included as Submodule**: It lives in `lib/gofr-common/`.
*   **Editable**: Any changes you make in `lib/gofr-common/` take effect immediately.

## 3. Running Code (The Rules)

Do not run `pytest` or `python` directly. We use helper scripts to ensure all paths and variables are correct.

| Task | Command |
| :--- | :--- |
| **Run Tests** | `./scripts/run_tests.sh` |
| **Make Token** | `source <(./lib/gofr-common/scripts/auth_env.sh --docker) && ./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups <group> --name <name>` |
| **Restart (prod stack)** | `./docker/stop-prod.sh && ./docker/start-prod.sh` |
| **Backup** | `./scripts/backup_now.sh` |

## 4. Coding Style

*   **Logging**: Never use `print()`. Use `logger.info()`.
*   **Config**: Never hardcode paths. Use `Config` objects.
*   **Validation**: Use Pydantic models for data.

## 5. IDE Setup

We standardize on VS Code.
*   **Debugging**: Use the pre-configured "Run and Debug" profiles.
*   **Linting**: Ruff and Black run automatically on save.
