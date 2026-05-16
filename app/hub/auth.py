"""Helpers for resolving callback tokens to registered service principals."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.logger import get_logger

if TYPE_CHECKING:
    from app.services.registry import ServiceRegistry

logger = get_logger("gofr-agent.hub.auth")


@dataclass(frozen=True)
class ServicePrincipal:
    service_name: str
    result_types: tuple[str, ...] = ()
    can_publish: bool = False
    can_consume: bool = False


def resolve_service_principal(
    token: str,
    registry: ServiceRegistry,
) -> ServicePrincipal | None:
    """Resolve a callback token to its registered service principal."""
    if not token:
        return None

    for service_config in registry.all_service_configs:
        callback_token = service_config.hub_callback_token
        if not callback_token:
            continue
        if not secrets.compare_digest(callback_token, token):
            continue

        capabilities = registry.service_hub_capabilities(service_config.name)
        logger.debug("Resolved hub callback principal", service=service_config.name)
        return ServicePrincipal(
            service_name=service_config.name,
            result_types=capabilities.result_types,
            can_publish=capabilities.can_publish_results,
            can_consume=capabilities.can_consume_results,
        )

    return None
