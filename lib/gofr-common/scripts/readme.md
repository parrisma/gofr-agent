# Auth Manager Scripts

Quick reference for Vault auth management with zero secrets written to disk.

## Setup (One-Time)

```bash
cd /path/to/gofr-iq
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
```

This command:
1. Reads your `secrets/vault_root_token` (stored securely during bootstrap)
2. Mints a short-lived operator token (1 hour TTL by default) with `gofr-mcp-policy`
3. Reads the JWT signing secret from Vault
4. Exports: `VAULT_ADDR`, `VAULT_TOKEN` (short-lived), `GOFR_JWT_SECRET`

**Note:** No secrets are written to disk; all held in memory for that shell session.

## Usage

### List Groups
```bash
./lib/gofr-common/scripts/auth_manager.sh --docker groups list
```

Output:
```
Name                      Status       Reserved   Created             
----------------------------------------------------------------------
admin                     active       yes        2026-01-19 15:12    
public                    active       yes        2026-01-19 15:12    

Total: 2 groups
```

### List Tokens
```bash
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
```

Output:
```
Name                   ID                                     Status     Groups                 Expires        
-------------------------------------------------------------------------------------------------------------------
                       06196d2c-807b-4ab9-8040-3c598094e33f   active     public                 364d 23h       
                       ab4d1f47-101f-47ae-962a-2f1b9d59d0f2   active     admin                  364d 23h       

Total: 2 tokens
```

### Create a Token
```bash
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
  --groups admin \
  --name "my-admin-token" \
  --ttl 30d
```

### Inspect a Token
```bash
./lib/gofr-common/scripts/auth_manager.sh --docker tokens inspect \
  --name "my-admin-token"
```

### Revoke a Token
```bash
./lib/gofr-common/scripts/auth_manager.sh --docker tokens revoke \
  --name "my-admin-token"
```

## Advanced Options

### auth_env.sh Flags

```bash
# Use custom Vault address
./lib/gofr-common/scripts/auth_env.sh --vault-addr http://vault.example.com:8200

# Mint token with different policy (default: gofr-mcp-policy)
./lib/gofr-common/scripts/auth_env.sh --policy my-custom-policy

# Longer token TTL (default: 1h)
./lib/gofr-common/scripts/auth_env.sh --ttl 8h

# All together
source <(./lib/gofr-common/scripts/auth_env.sh --docker --ttl 4h --policy gofr-mcp-policy)
```

### auth_manager.sh Flags

```bash
# Use different Vault backend (default: vault)
./lib/gofr-common/scripts/auth_manager.sh --backend memory groups list

# Output as JSON
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list --format json
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│ Shell Session                                   │
│                                                 │
│  $ source <(auth_env.sh --docker)              │
│    ├─ Load secrets/vault_root_token (ephemeral)│
│    ├─ Mint operator token (1h TTL)             │
│    ├─ Read JWT secret from Vault               │
│    └─ Export VAULT_ADDR, VAULT_TOKEN, JWT_*    │
│                                                 │
│  $ auth_manager.sh --docker groups list        │
│    ├─ Use VAULT_TOKEN (short-lived, safe)      │
│    ├─ Query Vault KV for group objects         │
│    └─ Display in formatted table               │
└─────────────────────────────────────────────────┘
```

**Zero-Trust Pattern:**
- Root token never leaves `secrets/vault_root_token`
- Operator token is short-lived (1h) and renewable
- Service tokens (AppRole) are per-service with least-privilege policies
- All secrets flow through Vault; nothing cached on disk

## Troubleshooting

### "Vault CLI not found"
If you don't have `vault` CLI on your host, the script falls back to `docker exec gofr-vault vault`. Make sure gofr-vault container is running:
```bash
docker ps | grep gofr-vault
```

### "Failed to read JWT secret from Vault"
Ensure Vault is running and the key exists:
```bash
docker exec -e VAULT_TOKEN=$(cat secrets/vault_root_token) -e VAULT_ADDR=http://127.0.0.1:8201 gofr-vault \
  vault kv get secret/gofr/config/jwt-signing-secret
```

### "GOFR_JWT_SECRET environment variable is required"
You forgot to run `auth_env.sh` first. Do:
```bash
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
```

## One-Liner Reference

```bash
# List groups
source <(./lib/gofr-common/scripts/auth_env.sh --docker) && ./lib/gofr-common/scripts/auth_manager.sh --docker groups list

# List tokens
source <(./lib/gofr-common/scripts/auth_env.sh --docker) && ./lib/gofr-common/scripts/auth_manager.sh --docker tokens list

# Create admin token
source <(./lib/gofr-common/scripts/auth_env.sh --docker) && ./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups admin --name prod-admin
```
