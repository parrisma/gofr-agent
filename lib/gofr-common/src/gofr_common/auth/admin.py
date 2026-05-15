"""
Vault Administration
====================
Provides "God Mode" capabilities to configure Vault Auth Methods and Roles.
Used by bootstrap and setup scripts, NOT by runtime applications.
"""

from typing import Dict, List

from .backends.vault_client import VaultClient, VaultError
from .policies import POLICIES


class VaultAdminError(VaultError):
    """Raised when admin operations fail."""
    pass

class VaultAdmin:
    """Administrator interface for Vault configuration.

    Handles:
    - Enabling Auth Methods (AppRole)
    - Managing Policies
    - creating/Updating AppRoles
    - Generating SecretIDs
    """

    def __init__(self, client: VaultClient):
        self.client = client
        self._hvac = client._client # Access underlying hvac client

    def enable_approle_auth(self, mount_point: str = "approle") -> None:
        """Enable the AppRole auth method if not already enabled."""
        try:
            auth_methods = self._hvac.sys.list_auth_methods()
            path = f"{mount_point}/"

            if path in auth_methods:
                # check if it's actually approle
                if auth_methods[path]['type'] == 'approle':
                    return

            self._hvac.sys.enable_auth_method(
                method_type="approle",
                path=mount_point,
                description="GOFR AppRole Auth"
            )
        except Exception as e:
            raise VaultAdminError(f"Failed to enable AppRole auth: {e}") from e

    def update_policies(self) -> None:
        """Upload all defined HCL policies to Vault."""
        try:
            for name, hcl in POLICIES.items():
                self._hvac.sys.create_or_update_policy(
                    name=name,
                    policy=hcl
                )
        except Exception as e:
            raise VaultAdminError(f"Failed to update policies: {e}") from e

    def provision_service_role(
        self,
        service_name: str,
        policy_name: str,
        additional_policy_names: List[str] | None = None,
        token_ttl: str = "1h",
        token_max_ttl: str = "24h"
    ) -> None:
        """Create or update an AppRole for a service.

        Args:
            service_name: Name of the role (e.g. 'gofr-mcp')
            policy_name: Name of the policy to attach (e.g. 'gofr-mcp-policy')
            additional_policy_names: Additional policy names to attach
            token_ttl: Default TTL for tokens issued to this role
            token_max_ttl: Max TTL for tokens issued to this role
        """
        try:
            token_policies = ["default", policy_name]
            if additional_policy_names:
                token_policies.extend(additional_policy_names)
            self._hvac.auth.approle.create_or_update_approle(
                role_name=service_name,
                token_policies=token_policies,
                token_ttl=token_ttl,
                token_max_ttl=token_max_ttl,
                bind_secret_id=True,
                token_bound_cidrs=[],
                secret_id_num_uses=0, # Unlimited uses (relies on rotation)
                secret_id_ttl="0",    # Unlimited TTL (relies on rotation)
            )
        except Exception as e:
            raise VaultAdminError(f"Failed to provision role {service_name}: {e}") from e

    def generate_service_credentials(self, service_name: str) -> Dict[str, str]:
        """Generate a new SecretID and retrieve the RoleID.

        Returns:
            Dict containing 'role_id' and 'secret_id'
        """
        try:
            # Get Role ID
            role_resp = self._hvac.auth.approle.read_role_id(role_name=service_name)
            role_id = role_resp['data']['role_id']

            # Generate Secret ID
            # Note: We do not use wrapped responses here as we are writing to a secure volume
            secret_resp = self._hvac.auth.approle.generate_secret_id(role_name=service_name)
            secret_id = secret_resp['data']['secret_id']

            return {
                "role_id": role_id,
                "secret_id": secret_id
            }
        except Exception as e:
            raise VaultAdminError(f"Failed to generate credentials for {service_name}: {e}") from e
