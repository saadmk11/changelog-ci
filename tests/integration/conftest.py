import json
import shlex
import sys
from pathlib import Path

import pytest

from tests.git import command
from tests.github import pull_request_event


@pytest.fixture(autouse=True)
def runner_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    event = tmp_path_factory.mktemp("events") / "event.json"
    event.write_text(
        json.dumps({"repository": {"full_name": "o/r", "default_branch": "main"}})
    )
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REF": "refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    return event


@pytest.fixture
def pr_event(runner_environment: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    runner_environment.write_text(json.dumps(pull_request_event()))
    return runner_environment


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    workspace = tmp_path / "work"
    command(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    command(tmp_path, "init", "--initial-branch=main", str(workspace))
    (workspace / "CHANGELOG.md").write_text("old\n")
    (workspace / "other.txt").write_text("original\n")
    command(workspace, "add", "--", "CHANGELOG.md", "other.txt")
    command(workspace, "commit", "-m", "Initial")
    command(workspace, "remote", "add", "origin", remote.as_uri())
    command(workspace, "push", "-u", "origin", "main")
    command(workspace, "remote", "set-url", "origin", "git@github.com:o/r.git")
    monkeypatch.setenv(
        "GIT_SSH_COMMAND",
        shlex.join(
            [
                Path(sys.executable).as_posix(),
                Path(__file__).with_name("git_transport.py").as_posix(),
            ]
        ),
    )
    monkeypatch.setenv("GIT_SSH_VARIANT", "simple")
    monkeypatch.setenv("_CHANGELOG_CI_TEST_REMOTE", str(remote))
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    return workspace, remote
