import json
import subprocess
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from typer.testing import CliRunner

from gh_changelog_ci.actions.context import load_context
from gh_changelog_ci.actions.git import Git
from gh_changelog_ci.actions.github import comment, create_pull_request
from gh_changelog_ci.actions.runner import run
from gh_changelog_ci.cli import app
from gh_changelog_ci.config import resolve_actions
from gh_changelog_ci.errors import ConfigurationError
from gh_changelog_ci.github import GitHub
from gh_changelog_ci.log import TerminalReporter
from gh_changelog_ci.models import Settings


def unexpected(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail("Local execution reached a workflow operation")


@pytest.mark.parametrize("flag", [None, "false", "TRUE", "1"])
def test_local_actions_stop_before_dependency_and_configuration_loading(
    flag: str | None,
    cli_api: list[httpx.Request],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if flag is not None:
        monkeypatch.setenv("GITHUB_ACTIONS", flag)
    monkeypatch.setenv("_CHANGELOG_CI_COMPOSITE", "true")
    monkeypatch.setattr("gh_changelog_ci.cli.require_actions", unexpected)
    monkeypatch.setattr("gh_changelog_ci.cli.resolve_actions", unexpected)
    result = CliRunner().invoke(
        app, ["actions", "--config-file", "missing.json", "--dry-run"]
    )
    assert result.exit_code == 2, result.output
    assert "requires a GitHub Actions runner" in result.output
    assert not cli_api
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "operation", ["context", "config", "run", "git", "comment", "pr"]
)
def test_workflow_operations_reject_direct_local_calls(
    operation: str,
    github: GitHub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "event.json"))
    monkeypatch.setattr(Path, "read_bytes", unexpected)
    monkeypatch.setattr("gh_changelog_ci.config.load_file", unexpected)
    monkeypatch.setattr(GitHub, "request", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    with pytest.raises(ConfigurationError, match="requires a GitHub Actions runner"):
        match operation:
            case "context":
                load_context(Settings())
            case "config":
                resolve_actions({"config_file": "missing.json"}, {}, TerminalReporter())
            case "run":
                run(Settings(), github, TerminalReporter())
            case "git":
                Git(tmp_path / "missing", Settings())
            case "comment":
                comment(github, "o/r", 9, "body")
            case "pr":
                create_pull_request(github, "o/r", "title", "notes", "main", "body")
            case _:
                pytest.fail("Unknown operation")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("on_runner", [False, True])
def test_generate_never_runs_workflow_operations(
    on_runner: bool,
    cli_api: list[httpx.Request],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if on_runner:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "missing-event.json"))
    monkeypatch.setattr("gh_changelog_ci.actions.context.load_context", unexpected)
    monkeypatch.setattr("gh_changelog_ci.actions.runner.run", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "commit_changelog": True,
                "comment_changelog": True,
                "create_pull_request": True,
                "new_branch": "notes",
                "committer_username": "Unused identity",
                "pull_request_title_regex": "^NeverMatch$",
            }
        )
    )
    result = CliRunner().invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--config-file",
            str(config),
            "--stdout",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "# Version: 1\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    )
    assert [(request.method, request.url.path) for request in cli_api] == [
        ("GET", "/repos/o/r/releases/latest"),
        ("GET", "/search/issues"),
    ]
    assert list(tmp_path.iterdir()) == [config]


def test_local_generation_cannot_enable_workflow_reporting(
    cli_api: list[httpx.Request], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    monkeypatch.setattr("gh_changelog_ci.cli.require_actions", unexpected)
    result = CliRunner().invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--output-mode",
            "github",
            "--summary",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "requires a GitHub Actions runner" in result.output
    assert not cli_api
    assert not list(tmp_path.iterdir())
