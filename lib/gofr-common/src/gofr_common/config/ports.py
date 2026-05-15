"""
GOFR Service Port Configuration
================================

Centralized port allocation for all GOFR services.

Port Allocation Strategy:
- Each service gets a base port in increments of 10
- MCP (Model Context Protocol) = base + 0
- MCPO (MCP Orchestrator) = base + 1
- Web (Web UI/API) = base + 2

This ensures:
1. Consistent port spacing across all services
2. Easy addition of new services
3. No port conflicts
4. Clear service identification by port range
"""

from pathlib import Path
from typing import Dict, Mapping, NamedTuple, Optional

from gofr_common.config.env_loader import EnvLoader


class ServicePorts(NamedTuple):
    """Port configuration for a single service."""

    mcp: int
    mcpo: int
    web: int

    @property
    def base(self) -> int:
        """Return the base port for this service."""
        return self.mcp

    def as_dict(self) -> Dict[str, int]:
        """Return ports as dictionary."""
        return {
            'mcp': self.mcp,
            'mcpo': self.mcpo,
            'web': self.web
        }

    def as_env_dict(self, prefix: str) -> Dict[str, str]:
        """
        Return ports as environment variable dictionary.

        Args:
            prefix: Environment variable prefix (e.g., 'GOFR_DOC')

        Returns:
            Dictionary of environment variables
        """
        return {
            f'{prefix}_MCP_PORT': str(self.mcp),
            f'{prefix}_MCPO_PORT': str(self.mcpo),
            f'{prefix}_WEB_PORT': str(self.web)
        }


_PORT_ENV_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "config" / "gofr_ports.env",
    Path(__file__).resolve().parent / "gofr_ports.env",
]

# Port allocation starts at 8040 with increments of 10
_BASE_PORT = 8040
_PORT_INCREMENT = 10

# Defaults used if the env file is missing a value
_DEFAULT_PORTS = {
    'gofr-doc': ServicePorts(mcp=8040, mcpo=8041, web=8042),
    'gofr-plot': ServicePorts(mcp=8050, mcpo=8051, web=8052),
    'gofr-np': ServicePorts(mcp=8060, mcpo=8061, web=8062),
    'gofr-dig': ServicePorts(mcp=8070, mcpo=8071, web=8072),
    'gofr-iq': ServicePorts(mcp=8080, mcpo=8081, web=8082),
    'gofr-agent': ServicePorts(mcp=8090, mcpo=8091, web=8092),
}

_PORT_CACHE: Optional[Dict[str, ServicePorts]] = None


def _parse_port(env_data: Mapping[str, str], key: str, default: int) -> int:
    value = env_data.get(key)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Invalid port for {key}: {value}") from exc


def _resolve_env_path(env_file: Optional[Path]) -> Path:
    if env_file:
        candidate = Path(env_file)
        if candidate.exists():
            return candidate

    for candidate in _PORT_ENV_CANDIDATES:
        if candidate.exists():
            return candidate

    return _PORT_ENV_CANDIDATES[0]


def _build_ports(env_file: Optional[Path], env_overrides: Optional[Mapping[str, str]]) -> Dict[str, ServicePorts]:
    loader = EnvLoader(_resolve_env_path(env_file))
    env_data = loader.load(overrides=env_overrides)

    def ports_for(service: str, defaults: ServicePorts) -> ServicePorts:
        prefix = service.replace('-', '_').upper()
        return ServicePorts(
            mcp=_parse_port(env_data, f"{prefix}_MCP_PORT", defaults.mcp),
            mcpo=_parse_port(env_data, f"{prefix}_MCPO_PORT", defaults.mcpo),
            web=_parse_port(env_data, f"{prefix}_WEB_PORT", defaults.web),
        )

    return {name: ports_for(name, defaults) for name, defaults in _DEFAULT_PORTS.items()}


def load_ports(
    env_file: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    force_reload: bool = False,
) -> Dict[str, ServicePorts]:
    """Load ports from .env data with optional overrides.

    If env is provided, a fresh map is returned (no cache). Otherwise values are cached.
    """
    global _PORT_CACHE

    if env is not None or force_reload:
        return _build_ports(env_file, env)

    if _PORT_CACHE is None:
        _PORT_CACHE = _build_ports(env_file, env)

    return _PORT_CACHE


def reset_ports_cache() -> None:
    """Clear cached port map (primarily for testing)."""
    global _PORT_CACHE
    _PORT_CACHE = None


def get_ports(service_name: str, env: Optional[Mapping[str, str]] = None) -> ServicePorts:
    """
    Get port configuration for a service.

    Args:
        service_name: Name of the service (e.g., 'gofr-doc')

    Returns:
        ServicePorts configuration

    Raises:
        KeyError: If service name is not registered
    """
    ports = load_ports(env=env)
    return ports[service_name]


def register_service(service_name: str, base_port: int) -> ServicePorts:
    """
    Register a new service with port allocation.

    Args:
        service_name: Name of the service
        base_port: Base port for the service (must be multiple of 10)

    Returns:
        ServicePorts configuration

    Raises:
        ValueError: If base_port is not valid or conflicts with existing
    """
    if base_port % 10 != 0:
        raise ValueError(f"Base port must be a multiple of 10, got {base_port}")

    global _PORT_CACHE
    ports_map = load_ports()

    # Check for conflicts
    for name, ports in ports_map.items():
        if ports.base == base_port:
            raise ValueError(
                f"Port {base_port} already allocated to service '{name}'"
            )
        if base_port < ports.base + 3 and base_port + 3 > ports.base:
            raise ValueError(
                f"Port range {base_port}-{base_port+2} conflicts with "
                f"service '{name}' ({ports.base}-{ports.base+2})"
            )

    service_ports = ServicePorts(mcp=base_port, mcpo=base_port + 1, web=base_port + 2)
    ports_map[service_name] = service_ports
    reset_ports_cache()
    _PORT_CACHE = ports_map
    return service_ports


def list_services() -> Dict[str, ServicePorts]:
    """
    List all registered services and their ports.

    Returns:
        Dictionary of service names to ServicePorts
    """
    return load_ports().copy()


def next_available_base() -> int:
    """
    Get the next available base port.

    Returns:
        Next available base port (multiple of 10)
    """
    ports_map = load_ports()

    if not ports_map:
        return _BASE_PORT

    max_base = max(ports.base for ports in ports_map.values())
    return max_base + _PORT_INCREMENT


# Convenience accessors for each service
PORTS = load_ports()
GOFR_DOC_PORTS = PORTS['gofr-doc']
GOFR_PLOT_PORTS = PORTS['gofr-plot']
GOFR_NP_PORTS = PORTS['gofr-np']
GOFR_DIG_PORTS = PORTS['gofr-dig']
GOFR_IQ_PORTS = PORTS['gofr-iq']
GOFR_AGENT_PORTS = PORTS['gofr-agent']


__all__ = [
    'ServicePorts',
    'PORTS',
    'load_ports',
    'reset_ports_cache',
    'get_ports',
    'register_service',
    'list_services',
    'next_available_base',
    'GOFR_DOC_PORTS',
    'GOFR_PLOT_PORTS',
    'GOFR_NP_PORTS',
    'GOFR_DIG_PORTS',
    'GOFR_IQ_PORTS',
    'GOFR_AGENT_PORTS',
]
