# Authentication System

This system handles security for all GOFR services, ensuring only authorized users and scripts can access data.

## Concepts

*   **Tokens**: Secure keys (JWTs) that you include with requests to prove who you are.
*   **Groups**: Permissions. A token has a list of groups (e.g., `["admin", "reporting"]`) which determine what it can do.
*   **Vault**: The secure safe where tokens and secret keys are stored.

## Usage

### 1. Generating Tokens

You use the command-line tool to create tokens for users or services.

```bash
# Generate a token with admin access
python -m gofr_common.auth.cli token create --groups admin
```

### 2. Checking Tokens

In your code, you don't check signatures manually. You just ask the system "is this valid?"

```python
# In a route handler
def get_data(token = Depends(auth.verify_token)):
    print(f"User has groups: {token.groups}")
```

## Configuration

The system is configured via environment variables (usually set in `.env` or Docker files).

*   `GOFR_AUTH_BACKEND`: Where to store data (`vault`, `file`, or `memory`).
*   `GOFR_VAULT_ADDR`: Address of the Vault server. 
*   `GOFR_DIG_JWT_SECRET`: The secret key used to sign tokens.

For deep technical details on the token format and verification capability, see the source code in `gofr_common.auth`.
