"""Application settings for gofr-agent.

Re-exports gofr_common.config.Settings with GOFR_AGENT prefix.
"""

from gofr_common.config import Settings
from gofr_common.config import get_settings as _get_settings

_ENV_PREFIX = "GOFR_AGENT"


def get_settings(reload: bool = False, require_auth: bool = True) -> Settings:
    """Return the global Settings instance for GOFR_AGENT."""
    return _get_settings(
        prefix=_ENV_PREFIX,
        reload=reload,
        require_auth=require_auth,
    )


__all__ = ["Settings", "get_settings"]
