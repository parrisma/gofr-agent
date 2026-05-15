# VS Code Launch Configuration Standards

To ensure a consistent developer experience across all GOFR projects (`gofr-dig`, `gofr-doc`, `gofr-plot`, `gofr-np`, `gofr-iq`), we are consolidating the `.vscode/launch.json` configurations.

**Related:**
- Overall dev rules: [docs/technical/gofr_development_standards.md](lib/gofr-common/docs/technical/gofr_development_standards.md).
- Port numbers for MCP/Web: [docs/config/port_standardization.md](lib/gofr-common/docs/config/port_standardization.md).

## The Standard Configuration

Every project's `launch.json` **MUST** include the following core configurations. Copy the template below and replace the `[PLACEHOLDERS]` with project-specific values.

### Template

```jsonc
{
    "version": "0.2.0",
    "configurations": [
        // ====================================================================
        // 1. TEST RUNNERS (Standard Scripts)
        // ====================================================================
        {
            "name": "Run All Tests",
            "type": "node-terminal",
            "request": "launch",
            "command": "bash scripts/run_tests.sh",
            "cwd": "${workspaceFolder}"
        },
        {
            "name": "Run Tests (Verbose)",
            "type": "node-terminal",
            "request": "launch",
            "command": "bash scripts/run_tests.sh -v",
            "cwd": "${workspaceFolder}"
        },

        // ====================================================================
        // 2. DEBUGGING - MCP SERVER
        // ====================================================================
        {
            "name": "Debug: MCP Server (No Auth)",
            "type": "debugpy",
            "request": "launch",
            "module": "app.main_mcp",
            "args": [
                "--port", "[MCP_PORT]",
                "--no-auth"
            ],
            "cwd": "${workspaceFolder}",
            "console": "integratedTerminal",
            "justMyCode": true,
            "env": {
                "[ENV_PREFIX]_ENV": "TEST",
                "PYTHONPATH": "${workspaceFolder}"
            }
        },
        {
            "name": "Debug: MCP Server (With Auth)",
            "type": "debugpy",
            "request": "launch",
            "module": "app.main_mcp",
            "args": [
                "--port", "[MCP_PORT]",
                "--jwt-secret", "test-secret-key-for-secure-testing-do-not-use-in-production",
                "--token-store", "${workspaceFolder}/logs/[PROJECT_NAME]_tokens_test.json"
            ],
            "cwd": "${workspaceFolder}",
            "console": "integratedTerminal",
            "justMyCode": true,
            "env": {
                "[ENV_PREFIX]_ENV": "TEST",
                "PYTHONPATH": "${workspaceFolder}"
            }
        },

        // ====================================================================
        // 3. DEBUGGING - WEB SERVER
        // ====================================================================
        {
            "name": "Debug: Web Server (No Auth)",
            "type": "debugpy",
            "request": "launch",
            "module": "app.main_web",
            "args": [
                "--port", "[WEB_PORT]",
                "--no-auth"
            ],
            "cwd": "${workspaceFolder}",
            "console": "integratedTerminal",
            "justMyCode": true,
            "env": {
                "[ENV_PREFIX]_ENV": "TEST",
                "PYTHONPATH": "${workspaceFolder}"
            }
        },
        {
            "name": "Debug: Web Server (With Auth)",
            "type": "debugpy",
            "request": "launch",
            "module": "app.main_web",
            "args": [
                "--port", "[WEB_PORT]",
                "--jwt-secret", "test-secret-key-for-secure-testing-do-not-use-in-production",
                "--token-store", "${workspaceFolder}/logs/[PROJECT_NAME]_tokens_test.json"
            ],
            "cwd": "${workspaceFolder}",
            "console": "integratedTerminal",
            "justMyCode": true,
            "env": {
                "[ENV_PREFIX]_ENV": "TEST",
                "PYTHONPATH": "${workspaceFolder}"
            }
        },

        // ====================================================================
        // 4. UTILITIES
        // ====================================================================
        {
            "name": "Utility: Create Token",
            "type": "node-terminal",
            "request": "launch",
            "command": "bash -lc 'source <(./lib/gofr-common/scripts/auth_env.sh --docker) && ./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups test_group --name vscode-launch'",
            "cwd": "${workspaceFolder}"
        }
    ]
}
```

## Project-Specific Values

When implementing this standard, replace the placeholders with the following values:

| Project | `[PROJECT_NAME]` | `[ENV_PREFIX]` | `[MCP_PORT]` | `[WEB_PORT]` |
| :--- | :--- | :--- | :--- | :--- |
| **gofr-dig** | `gofr-dig` | `GOFR_DIG` | `8030` | `8032` |
| **gofr-doc** | `gofr-doc` | `GOFR_DOC` | `8010` | `8012` |
| **gofr-plot** | `gofr-plot` | `GOFR_PLOT` | `8001` | `8000` |
| **gofr-np** | `gofr-np` | `GOFR_NP` | `8020` | `8022` |
| **gofr-iq** | `gofr-iq` | `GOFR_IQ` | `8050` | `8052` |

## Implementation Steps

1. Open `.vscode/launch.json` in the target project.
2. Backup the existing configuration if necessary.
3. Paste the template above.
4. Perform a Find & Replace for the placeholders (e.g., replace `[MCP_PORT]` with `8030` for `gofr-dig`).
5. Verify that `scripts/run_tests.sh` exists and is executable.
