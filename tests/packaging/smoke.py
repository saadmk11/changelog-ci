"""Exercise an installed distribution outside the source checkout."""

import importlib
import importlib.resources
import importlib.util
import os
import sys
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from gh_changelog_ci.cli import app
from gh_changelog_ci.github import GitHub


def response(request: httpx.Request) -> httpx.Response:
    """Return the two GitHub responses needed for standalone generation."""
    match request.url.path:
        case "/repos/o/r/releases/latest":
            return httpx.Response(200, json={"published_at": "2026-01-01T00:00:00Z"})
        case "/search/issues":
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "incomplete_results": False,
                    "items": [
                        {
                            "number": 1,
                            "title": "Installed package works",
                            "html_url": "https://github.com/o/r/pull/1",
                            "labels": [],
                            "created_at": "2026-01-02T00:00:00Z",
                        }
                    ],
                },
            )
        case _:
            raise AssertionError(f"Unexpected API request: {request.url.path}")


def client(api_url: str, token: str | None = None) -> GitHub:
    """Create an API client with the test transport."""
    return GitHub(api_url, token, transport=httpx.MockTransport(response))


def generation() -> None:
    """Verify generation runs without loading workflow code or invoking Git."""
    with (
        patch("gh_changelog_ci.cli.GitHub", client),
        patch("subprocess.run", side_effect=AssertionError("Generation invoked Git")),
    ):
        result = CliRunner().invoke(
            app,
            [
                "generate",
                "--repository",
                "o/r",
                "--release-version",
                "2.0.0",
                "--stdout",
            ],
        )
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "# Version: 2.0.0\n\n"
        "* [#1](https://github.com/o/r/pull/1): Installed package works\n"
    )
    assert result.stderr == ""
    assert "github_action_utils" not in sys.modules
    assert not any(name.startswith("gh_changelog_ci.actions") for name in sys.modules)


def base() -> None:
    """Verify a base installation can generate changelogs."""
    assert importlib.util.find_spec("github_action_utils") is None
    assert importlib.resources.files("gh_changelog_ci").joinpath("py.typed").is_file()
    generation()


def actions() -> None:
    """Verify the extra cannot enable local workflow operations."""
    assert importlib.util.find_spec("github_action_utils") is not None
    generation()
    result = CliRunner().invoke(app, ["actions"])
    assert result.exit_code == 2, result.output
    assert "requires a GitHub Actions runner" in result.output
    assert "github_action_utils" not in sys.modules
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
        importlib.import_module("gh_changelog_ci.actions.reporting")
        result = CliRunner().invoke(app, ["actions"])
    assert result.exit_code == 2, result.output
    assert "GITHUB_EVENT_NAME" in result.output
    assert "Install the optional integration" not in result.output


if __name__ == "__main__":
    match sys.argv[1]:
        case "base":
            base()
        case "actions":
            actions()
        case _:
            raise ValueError("Expected base or actions smoke test")
