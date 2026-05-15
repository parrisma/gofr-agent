# AppRole Provisioning Config Schema (JSON)

This schema defines how a GOFR project declares the Vault AppRoles it needs.

## Location (per project)
Recommended location in each project repo:
- `config/gofr_approles.json`

## Fields
Required:
- `schema_version` (number): schema version (currently `1`).
- `project` (string): human-readable project identifier (example: `gofr-dig`).
- `roles` (array): list of AppRoles to ensure.

Optional (with defaults):
- `mount_point` (string): Vault AppRole mount point. Default: `approle`.
- `token_ttl` (string): default token TTL for roles. Default: `1h`.
- `token_max_ttl` (string): default max token TTL. Default: `24h`.
- `credentials_output_dir` (string): relative path (from project root) where credential JSON files are written. Default: `secrets/service_creds`.

Role object fields:
- `role_name` (string): Vault AppRole name (per PROJECT).
- `policies` (array of strings): Vault policy names to attach. First item is treated as primary; remaining are additional policies.
- `credentials_filename` (string, optional): output filename without `.json` if it should differ from `role_name`.

## Example
See the gofr-dig example:
- `config/gofr_approles.json`
