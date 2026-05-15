"""
Vault Access Policies
=====================
Defines HCL policies for service isolation (Least Privilege).

These policies are applied by VaultAdmin to restrict what each AppRole can access.
"""

# Base policy for all GOFR services - read shared config
POLICY_GLOBAL_READ = """
# Read global configuration (non-sensitive)
path "secret/data/global/config" {
  capabilities = ["read"]
}
"""

# Shared runtime config policy (read-only)
POLICY_GOFR_CONFIG_RUNTIME_READ = """
# Read GOFR shared config (JWT signing, etc)
path "secret/data/gofr/config/*" {
  capabilities = ["read"]
}
"""

# Runtime auth-read policy (read-only)
# Needed for services to verify tokens and read group membership.
POLICY_GOFR_AUTH_RUNTIME_READ = """
# Read GOFR auth data (groups, tokens, indexes, etc)
path "secret/data/gofr/auth/*" {
  capabilities = ["read"]
}
# Optional metadata listing for auth paths (read-only)
path "secret/metadata/gofr/auth/*" {
  capabilities = ["list", "read"]
}
"""

# Admin auth management policy (write access)
POLICY_GOFR_AUTH_ADMIN = """
# Read/write GOFR auth data (groups, tokens, etc) for admin control role
path "secret/data/gofr/auth/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
# List auth paths
path "secret/metadata/gofr/auth/*" {
  capabilities = ["list", "read"]
}
"""

# Backward-compatible alias for existing imports.
POLICY_GOFR_CONFIG_READ = POLICY_GOFR_CONFIG_RUNTIME_READ

# Dedicated logging secrets policy (least privilege for sink credentials)
POLICY_GOFR_DIG_LOGGING_READ = """
# Read GOFR-DIG logging sink secrets
path "secret/data/gofr/config/logging/*" {
  capabilities = ["read"]
}
# Optional metadata listing for operational tooling
path "secret/metadata/gofr/config/logging/*" {
  capabilities = ["list", "read"]
}
"""

# MCP Service Policy
# - Read own secrets (OpenRouter keys, etc)
# - Read global config
# - Read GOFR shared config (JWT signing)
POLICY_MCP_READ = (
    """
# Read MCP-specific secrets
path "secret/data/services/mcp/*" {
  capabilities = ["read"]
}
# Read specific token for this service if needed
path "secret/data/tokens/mcp" {
  capabilities = ["read"]
}
"""
    + POLICY_GLOBAL_READ
    + POLICY_GOFR_CONFIG_READ
    + POLICY_GOFR_AUTH_RUNTIME_READ
)

# Web Service Policy
# - Read own secrets (Session keys, etc)
# - Read global config
# - Read GOFR shared config (JWT signing)
POLICY_WEB_READ = (
    """
# Read Web-specific secrets
path "secret/data/services/web/*" {
  capabilities = ["read"]
}
# Read specific token for this service if needed
path "secret/data/tokens/web" {
  capabilities = ["read"]
}
"""
    + POLICY_GLOBAL_READ
    + POLICY_GOFR_CONFIG_READ
    + POLICY_GOFR_AUTH_RUNTIME_READ
)

# DIG Service Policy
# - Read own secrets (API keys, etc)
# - Read global config
# - Read GOFR shared config (JWT signing)
POLICY_DIG_READ = (
    """
# Read DIG-specific secrets
path "secret/data/services/dig/*" {
  capabilities = ["read"]
}
# Read specific token for this service if needed
path "secret/data/tokens/dig" {
  capabilities = ["read"]
}
"""
    + POLICY_GLOBAL_READ
    + POLICY_GOFR_CONFIG_READ
    + POLICY_GOFR_AUTH_RUNTIME_READ
)

# DOC Service Policy
# - Read own secrets (API keys, etc)
# - Read global config
# - Read GOFR shared config (JWT signing)
# - Read/write GOFR auth data (groups, tokens) for doc-level auth
POLICY_DOC_READ = (
    """
# Read DOC-specific secrets
path "secret/data/services/doc/*" {
  capabilities = ["read"]
}
# Read specific token for this service if needed
path "secret/data/tokens/doc" {
  capabilities = ["read"]
}
# Read/write shared GOFR auth data (groups, tokens)
path "secret/data/gofr/auth/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "secret/metadata/gofr/auth/*" {
  capabilities = ["list", "read", "delete"]
}
"""
    + POLICY_GLOBAL_READ
    + POLICY_GOFR_CONFIG_READ
    + POLICY_GOFR_AUTH_RUNTIME_READ
)

# NP Service Policy
# - Read own secrets (if any)
# - Read global config
# - Read GOFR shared config (JWT signing)
POLICY_NP_READ = (
    """
# Read NP-specific secrets
path "secret/data/services/np/*" {
  capabilities = ["read"]
}
# Read specific token for this service if needed
path "secret/data/tokens/np" {
  capabilities = ["read"]
}
"""
    + POLICY_GLOBAL_READ
    + POLICY_GOFR_CONFIG_READ
    + POLICY_GOFR_AUTH_RUNTIME_READ
)

# Admin Control Policy
# - Read GOFR shared config
# - Read/write GOFR auth data
POLICY_ADMIN_CONTROL = POLICY_GLOBAL_READ + POLICY_GOFR_CONFIG_RUNTIME_READ + POLICY_GOFR_AUTH_ADMIN

# Map of policy name -> HCL content
POLICIES = {
    "gofr-mcp-policy": POLICY_MCP_READ,
    "gofr-web-policy": POLICY_WEB_READ,
    "gofr-dig-policy": POLICY_DIG_READ,
    "gofr-dig-logging-policy": POLICY_GOFR_DIG_LOGGING_READ,
    "gofr-doc-policy": POLICY_DOC_READ,
    "gofr-np-policy": POLICY_NP_READ,
    "gofr-admin-control-policy": POLICY_ADMIN_CONTROL,
}
