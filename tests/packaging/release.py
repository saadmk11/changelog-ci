"""Verify immutable tag, project version and production package pin agree."""

import re
import sys
import tomllib
from pathlib import Path


def validate_release(tag: str) -> str:
    """Validate the release tag, package version and Action requirement."""
    root = Path(__file__).resolve().parents[2]
    version: str = tomllib.loads((root / "pyproject.toml").read_text())["project"][
        "version"
    ]
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) or tag != f"v{version}":
        raise ValueError(
            "Release tag must be immutable vMAJOR.MINOR.PATCH "
            "and match package metadata."
        )
    action = (root / "action.yaml").read_text()
    requirements = re.findall(r"gh-changelog-ci\[actions\]==([0-9.]+)", action)
    if requirements != [version]:
        raise ValueError("Composite must pin exactly the released package version.")
    return version


if __name__ == "__main__":
    print(validate_release(sys.argv[1]))
