"""GitHub Actions integration."""

import os
from collections.abc import Mapping

from ..errors import ConfigurationError


def require_github_actions(env: Mapping[str, str] | None = None) -> None:
    """Require a runner before executing GitHub Actions operations."""
    # This guard must work before the optional Actions dependency is imported.
    if (os.environ if env is None else env).get("GITHUB_ACTIONS") != "true":
        raise ConfigurationError("This operation requires a GitHub Actions runner.")
