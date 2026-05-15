"""Authentication configuration utilities.

Previously provided resolve_auth_config() for resolving JWT secrets from
CLI arguments, environment variables, and defaults. These functions have
been removed -- JWT secrets are now always resolved via JwtSecretProvider
backed by Vault.

See JwtSecretProvider and create_vault_client_from_env for the replacement pattern.
"""
