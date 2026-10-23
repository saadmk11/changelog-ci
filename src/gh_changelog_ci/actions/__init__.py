"""GitHub Actions integration."""

import os
from collections.abc import Mapping

from ..errors import ConfigurationError


def escape(text: str) -> str:
    """Escape GitHub workflow command data."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def require_github_actions(env: Mapping[str, str] | None = None) -> None:
    """Require a runner before executing GitHub Actions operations."""
    if (os.environ if env is None else env).get("GITHUB_ACTIONS") != "true":
        raise ConfigurationError("This operation requires a GitHub Actions runner.")
