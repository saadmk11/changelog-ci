"""Validate both published artifacts in fresh environments outside the checkout."""

import email
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path


def check() -> None:
    """Validate artifact contents and fresh installations."""
    root = Path(__file__).resolve().parents[2]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = metadata["version"]
    assert not version.startswith("v")
    artifacts = [
        root / "dist" / f"gh_changelog_ci-{version}-py3-none-any.whl",
        root / "dist" / f"gh_changelog_ci-{version}.tar.gz",
    ]
    with zipfile.ZipFile(artifacts[0]) as wheel:
        names = wheel.namelist()
        assert "gh_changelog_ci/py.typed" in names
        assert any(name.endswith("/LICENSE") for name in names)
        assert not any(name.startswith(("scripts/", "tests/")) for name in names)
        info = email.message_from_bytes(
            wheel.read(f"gh_changelog_ci-{version}.dist-info/METADATA")
        )
        assert info["Name"] == "gh-changelog-ci" and info["Version"] == version
        assert info["Requires-Python"] == ">=3.11"
        assert info["License-Expression"] == "MIT"
        assert "What is Changelog CI?" in str(info.get_payload())
        requirements = info.get_all("Requires-Dist", [])
        assert any(
            "github-action-utils" in item
            and 'extra == "actions"' in item.replace("'", '"')
            for item in requirements
        )
    with tarfile.open(artifacts[1]) as sdist:
        names = sdist.getnames()
        prefix = f"gh_changelog_ci-{version}/"
        package_info = sdist.extractfile(prefix + "PKG-INFO")
        assert package_info is not None
        with package_info:
            info = email.message_from_bytes(package_info.read())
        assert info["Name"] == "gh-changelog-ci" and info["Version"] == version
        assert not any(name.startswith(prefix + "scripts/") for name in names)
        for obsolete in (
            "Dockerfile",
            ".dockerignore",
            "requirements.in",
            "requirements.txt",
            "requirements-test.in",
            "requirements-test.txt",
        ):
            assert prefix + obsolete not in names
        for file in (
            "README.md",
            "LICENSE",
            "pyproject.toml",
            "src/gh_changelog_ci/py.typed",
        ):
            assert any(name.endswith("/" + file) for name in names)
    subprocess.run(
        ["twine", "check", "--strict", *(str(path) for path in artifacts)], check=True
    )
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GITHUB_", "CHANGELOG_CI_", "INPUT_", "_CHANGELOG_CI_"))
    }
    with tempfile.TemporaryDirectory(prefix="changelog-ci-package-") as temporary:
        outside = Path(temporary)
        for index, artifact in enumerate(artifacts):
            environment = outside / f"venv{index}"
            subprocess.run(
                ["uv", "venv", "--python", sys.executable, str(environment)],
                check=True,
                cwd=outside,
            )
            python = environment / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), str(artifact)],
                check=True,
                cwd=outside,
            )
            console = environment / (
                "Scripts/gh-changelog-ci.exe"
                if os.name == "nt"
                else "bin/gh-changelog-ci"
            )
            result = subprocess.run(
                [str(console), "--version"],
                check=True,
                cwd=outside,
                capture_output=True,
                text=True,
            )
            assert result.stdout.strip() == version
            for args, expected in (
                ((), "generate"),
                (("generate",), "--repository"),
            ):
                help_result = subprocess.run(
                    [str(python), "-I", "-m", "gh_changelog_ci", *args, "--help"],
                    check=True,
                    cwd=outside,
                    capture_output=True,
                    text=True,
                )
                assert "Usage:" in help_result.stdout
                assert expected in help_result.stdout
                assert help_result.stderr == ""
            subprocess.run(
                [str(python), "-I", str(root / "tests/packaging/smoke.py"), "base"],
                check=True,
                cwd=outside,
                env=clean_env,
            )
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    str(artifact) + "[actions]",
                ],
                check=True,
                cwd=outside,
            )
            subprocess.run(
                [
                    str(python),
                    "-I",
                    str(root / "tests/packaging/smoke.py"),
                    "actions",
                ],
                check=True,
                cwd=outside,
                env=clean_env,
            )
    print("Wheel and sdist installation checks passed.")


if __name__ == "__main__":
    check()
