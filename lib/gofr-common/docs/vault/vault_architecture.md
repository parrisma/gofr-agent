# Vault Architecture

Vault is the "Bank" of the GOFR system. It securely stores passwords, keys, and tokens.

## Why Vault?

*   **Security**: Secrets (like API keys) are not stored in code or config files.
*   **Rotation**: We can change keys in one place without redeploying applications.
*   **Auditing**: We know exactly who accessed what secret and when.

## How it Works

1.  **Storage**: Vault runs as a secure container (`gofr-vault`) on port 8201.
2.  **Access**: Applications authenticate to Vault to "check out" the secrets they need.
3.  **Bootstrap**: When first set up, we run a script to initialize the vault and generate the first keys.

## Managing Vault

We provide a helper script for all Vault operations.

| Task | Command |
| :--- | :--- |
| **Start** | `./manage_vault.sh start` |
| **Unseal (Unlock)** | `./manage_vault.sh unseal` |
| **Check Health** | `./manage_vault.sh health` |
| **Reset (Danger)** | `./manage_vault.sh nuke` |

## Key Concepts

*   **Unsealing**: When Vault restarts, it is encrypted (sealed). An operator must "unseal" it using a key before applications can read secrets.
*   **AppRole**: The "Username/Password" for a machine or service (like `gofr-dig`).
