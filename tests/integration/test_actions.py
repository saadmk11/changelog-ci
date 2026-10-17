import importlib.util
import json
import shlex
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel, SecretStr, TypeAdapter
from typer.testing import CliRunner

from changelog_ci.actions.context import RunnerContext, load_context, release_version
from changelog_ci.actions.runner import run
from changelog_ci.cli import app
from changelog_ci.errors import APIError, ChangelogError, ConfigurationError, GitError
from changelog_ci.github import GitHub
from changelog_ci.models import Settings
from changelog_ci.reporting import TerminalReporter
from tests.git import command
from tests.github import pull_request_event, response

pytestmark = [
    pytest.mark.actions,
    pytest.mark.skipif(
        importlib.util.find_spec("github_action_utils") is None,
        reason="actions extra required",
    ),
]


class Outcome(BaseModel):
    event: str
    title: str
    version: str | None
    commit: bool
    comment: bool
    selected: str | None
    exit_code: int


OUTCOMES = TypeAdapter(list[Outcome]).validate_json(
    (Path(__file__).parents[1] / "fixtures/legacy/outcomes.json").read_bytes()
)


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_legacy_skip_and_version_outcomes(
    outcome: Outcome,
    github: GitHub,
    tmp_path: Path,
    runner_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", outcome.event)
    if outcome.event == "pull_request":
        runner_environment.write_text(
            json.dumps(pull_request_event(title=outcome.title))
        )
    settings = Settings(
        release_version=outcome.version,
        commit_changelog=outcome.commit,
        comment_changelog=outcome.comment,
        repository="o/r",
        workspace=tmp_path,
    )
    if outcome.exit_code == 1:
        message = (
            "release_version is required"
            if outcome.commit or outcome.comment
            else "commit_changelog and comment_changelog are both false"
        )
        with pytest.raises(ChangelogError, match=message) as error:
            run(settings, github, TerminalReporter(), legacy=True)
        assert error.value.exit_code == outcome.exit_code
    else:
        assert release_version(settings, load_context(settings)) == outcome.selected
        if outcome.selected is None:

            def unexpected(request: httpx.Request) -> httpx.Response:
                raise AssertionError("Skipped events must not call GitHub")

            with GitHub(
                "https://api.github.com", transport=httpx.MockTransport(unexpected)
            ) as client:
                run(settings, client, TerminalReporter(), legacy=True)


def test_context_uses_runner_payload(pr_event: Path) -> None:
    pr_event.write_text(
        json.dumps(
            pull_request_event(number=5, head="release", head_repository="fork/r")
        )
    )
    assert load_context(Settings(repository="o/r")) == RunnerContext(
        repository="o/r",
        is_pull_request=True,
        title="Release v2.0.0",
        number=5,
        head="release",
        base="main",
        head_repository="fork/r",
    )


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("refs/heads/releases/2.0", "releases/2.0"),
        ("refs/tags/v2.0.0", "main"),
        ("", "main"),
    ],
)
def test_dispatch_branch_does_not_depend_on_pr_refs(
    ref: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("GITHUB_HEAD_REF", "unrelated-head")
    monkeypatch.setenv("GITHUB_BASE_REF", "unrelated-base")
    assert load_context(Settings()) == RunnerContext(
        repository="o/r", is_pull_request=False, base=expected
    )


@pytest.mark.parametrize("missing", ["GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH"])
def test_missing_runner_event_context(
    missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(missing)
    with pytest.raises(ConfigurationError, match=missing):
        load_context(Settings())


def test_pr_event_requires_pr_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    with pytest.raises(ConfigurationError, match="Pull request data is missing"):
        load_context(Settings())


def test_removed_context_inputs_cannot_redirect_comments(
    pr_event: Path,
    cli_api: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "INPUT_EVENT_NAME": "workflow_dispatch",
        "INPUT_EVENT_PATH": "missing.json",
        "INPUT_PULL_REQUEST_NUMBER": "99",
        "INPUT_PULL_REQUEST_TITLE": "Release v9.0.0",
        "INPUT_HEAD_BRANCH": "wrong-head",
        "INPUT_BASE_BRANCH": "wrong-base",
    }.items():
        monkeypatch.setenv(key, value)
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--no-commit-changelog",
            "--comment-changelog",
            "--github-token",
            "secret",
        ],
    )
    assert result.exit_code == 0, result.output
    posts = [request for request in cli_api if request.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url.path == "/repos/o/r/issues/9/comments"
    assert json.loads(posts[0].content)["body"].startswith("# Version: v2.0.0\n")


@pytest.mark.parametrize("filename", ["CHANGELOG.rst", "releases/CHANGELOG.rst"])
def test_comment_only_without_git(
    cli_api: list[httpx.Request], tmp_path: Path, filename: str, pr_event: Path
) -> None:
    args = [
        "actions",
        "--no-commit-changelog",
        "--comment-changelog",
        "--github-token",
        "secret",
        "--changelog-filename",
        filename,
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    posts = [request for request in cli_api if request.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url.path == "/repos/o/r/issues/9/comments"
    expected = {
        "body": "# Version: v2.0.0\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    }
    assert json.loads(posts[0].content) == expected
    assert not list(tmp_path.iterdir())
    rerun = CliRunner().invoke(app, args)
    assert rerun.exit_code == 0, rerun.output
    posts = [request for request in cli_api if request.method == "POST"]
    assert [request.url.path for request in posts] == [
        "/repos/o/r/issues/9/comments",
        "/repos/o/r/issues/9/comments",
    ]
    assert [json.loads(request.content) for request in posts] == [expected, expected]
    assert not list(tmp_path.iterdir())


def test_actions_dry_run_suppresses_comment_and_files(
    cli_api: list[httpx.Request], tmp_path: Path, pr_event: Path
) -> None:
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--no-commit-changelog",
            "--comment-changelog",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "would append a PR comment" in result.stderr
    assert result.stdout == (
        "# Version: v2.0.0\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    )
    assert all(request.method == "GET" for request in cli_api)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "status,legacy,raises",
    [
        (422, True, False),
        (500, True, False),
        (403, True, True),
        (401, True, True),
        (422, False, True),
    ],
)
def test_comment_failure_mapping(
    status: int,
    legacy: bool,
    raises: bool,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    pr_event: Path,
) -> None:
    pr_event.write_text(json.dumps(pull_request_event(title="Release 2.0.0", number=1)))
    posts: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(status, text="secret")
        return response(request)

    settings = Settings(
        commit_changelog=False,
        comment_changelog=True,
        github_token=SecretStr("secret"),
        repository="o/r",
        workspace=tmp_path,
    )
    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        if raises:
            with pytest.raises(APIError, match=str(status)):
                run(settings, github, TerminalReporter(), legacy=legacy)
        else:
            run(settings, github, TerminalReporter(), legacy=legacy)
            assert str(status) in capsys.readouterr().err
    assert len(posts) == 1
    assert posts[0].url.path == "/repos/o/r/issues/1/comments"


def test_explicit_inconsistent_creation_fails_before_reads(
    cli_api: list[httpx.Request],
) -> None:
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--release-version",
            "1",
            "--no-commit-changelog",
            "--comment-changelog",
            "--create-pull-request",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "Creating a pull request requires committing." in result.output
    assert not cli_api


def test_non_pr_comment_remains_warning(
    github: GitHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(
        Settings(
            commit_changelog=False,
            comment_changelog=True,
            release_version="1",
            repository="o/r",
            workspace=tmp_path,
        ),
        github,
        TerminalReporter(),
        legacy=True,
    )
    assert "only supported" in capsys.readouterr().err


@pytest.mark.parametrize("payload", [None, b"{", b'{"pull_request": "secret"}'])
def test_invalid_event_is_clean_error(
    payload: bytes | None, runner_environment: Path
) -> None:
    if payload is None:
        runner_environment.unlink()
    else:
        runner_environment.write_bytes(payload)
    with pytest.raises(ConfigurationError, match="event payload") as error:
        load_context(Settings())
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("repository", [None, "invalid/secret/repository"])
def test_invalid_repository_in_runner_event(
    repository: str | None, runner_environment: Path
) -> None:
    runner_environment.write_text(
        json.dumps({"repository": {"full_name": repository} if repository else None})
    )
    with pytest.raises(ConfigurationError, match="[Rr]epository") as error:
        load_context(Settings())
    assert "secret" not in str(error.value)


def test_invalid_fork_repository_in_runner_event(pr_event: Path) -> None:
    pr_event.write_text(
        json.dumps(pull_request_event(head_repository="invalid/secret/repository"))
    )
    with pytest.raises(ConfigurationError, match="Invalid repository") as error:
        load_context(Settings(repository="o/r"))
    assert "secret" not in str(error.value)


def test_version_extracted_from_title_must_be_single_line() -> None:
    with pytest.raises(ConfigurationError, match="single-line"):
        release_version(
            Settings(version_regex=r"(?s)v.*"),
            RunnerContext(
                repository="o/r", is_pull_request=True, title="Release v1\nsecret"
            ),
        )


@pytest.mark.parametrize(
    "args,message",
    [
        (["--create-pull-request"], "PR creation requires a non-pull-request event"),
        (["--new-branch", "notes"], "New-PR overrides require"),
        (["--new-pull-request-title", "Notes"], "New-PR overrides require"),
        (
            ["--no-commit-changelog", "--comment-changelog"],
            "A GitHub token is required to comment",
        ),
    ],
)
def test_invalid_pr_operations_fail_before_collection(
    args: list[str], message: str, pr_event: Path, cli_api: list[httpx.Request]
) -> None:
    result = CliRunner().invoke(app, ["actions", *args])
    assert result.exit_code == 2, result.output
    assert message in result.output
    assert not cli_api


def test_comment_requires_number_before_collection(
    pr_event: Path, cli_api: list[httpx.Request]
) -> None:
    event = pull_request_event()
    event.pop("number")
    pr_event.write_text(json.dumps(event))
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--no-commit-changelog",
            "--comment-changelog",
            "--github-token",
            "secret",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "A pull request number is required to comment" in result.output
    assert not cli_api


@pytest.mark.parametrize("commit", [False, True])
def test_missing_pr_head_repository_never_falls_back_to_base_for_commits(
    commit: bool,
    pr_event: Path,
    repository: tuple[Path, Path],
    cli_api: list[httpx.Request],
) -> None:
    workspace, remote = repository
    pr_event.write_text(json.dumps(pull_request_event(head_repository=None)))
    before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--commit-changelog" if commit else "--no-commit-changelog",
            "--comment-changelog",
            "--github-token",
            "secret",
        ],
    )
    if commit:
        assert result.exit_code == 2, result.output
        assert "head repository is missing" in result.output
        assert not cli_api
    else:
        assert result.exit_code == 0, result.output
        posts = [request for request in cli_api if request.method == "POST"]
        assert len(posts) == 1
        assert posts[0].url.path == "/repos/o/r/issues/9/comments"
        assert json.loads(posts[0].content)["body"].startswith("# Version: v2.0.0\n")
    assert command(workspace, "show-ref") == before
    assert command(remote, "show-ref") == remote_before
    assert (workspace / "CHANGELOG.md").read_text() == "old\n"


def test_release_version_does_not_require_semver() -> None:
    settings = Settings(release_version="2026 October release")
    assert (
        release_version(
            settings, RunnerContext(repository="o/r", is_pull_request=False)
        )
        == "2026 October release"
    )


@pytest.mark.parametrize("create", [None, False, True])
def test_non_pr_commit_push_and_pr_options(
    repository: tuple[Path, Path], create: bool | None
) -> None:
    workspace, remote = repository
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response(request)

    settings = Settings(
        release_version="v2.0.0",
        changelog_filename="Change log.rst",
        github_token=SecretStr("secret"),
        repository="o/r",
        workspace=workspace,
        new_branch="release-notes",
        new_pull_request_title="Review these changes",
        commit_message="Add release notes",
        create_pull_request=create,
    )
    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        run(settings, github, TerminalReporter())
    assert (
        command(remote, "log", "-1", "release-notes", "--format=%s")
        == "Add release notes"
    )
    assert command(remote, "show", "release-notes:Change log.rst").startswith(
        "Version: v2.0.0\n"
    )
    posts = [r for r in requests if r.method == "POST"]
    if create is False:
        assert not posts
    else:
        assert len(posts) == 1
        payload = json.loads(posts[0].content)
        assert payload["title"] == "Review these changes"
        assert payload["head"] == "release-notes" and payload["base"] == "main"
        assert payload["body"].startswith("# Version: v2.0.0\n")


def test_default_branch_name_and_message(
    repository: tuple[Path, Path], github: GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, remote = repository
    monkeypatch.setattr("changelog_ci.actions.runner.time.time", lambda: 1234567890)
    run(
        Settings(
            release_version="v2.0.0",
            github_token=SecretStr("secret"),
            repository="o/r",
            workspace=workspace,
        ),
        github,
        TerminalReporter(),
    )
    assert (
        command(remote, "log", "-1", "changelog-ci-v2.0.0-1234567890", "--format=%s")
        == "[Changelog CI] Add Changelog for Version v2.0.0"
    )


def test_commit_dry_run_has_no_git_or_file_mutations(
    repository: tuple[Path, Path], cli_api: list[httpx.Request]
) -> None:
    workspace, remote = repository
    before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--release-version",
            "v2.0.0",
            "--dry-run",
            "--diff",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "+# Version: v2.0.0" in result.stdout
    assert command(workspace, "show-ref") == before
    assert command(remote, "show-ref") == remote_before
    assert command(remote, "show", "main:CHANGELOG.md") == "old"
    assert (workspace / "CHANGELOG.md").read_text() == "old\n"
    assert not (workspace / ".git/FETCH_HEAD").exists()
    assert cli_api
    assert all(request.method == "GET" for request in cli_api)


def test_config_file_dry_run_cannot_mutate(
    repository: tuple[Path, Path], cli_api: list[httpx.Request], tmp_path: Path
) -> None:
    workspace, remote = repository
    config = tmp_path / "settings.json"
    config.write_text('{"dry_run": true, "new_branch": "notes"}')
    before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--config-file",
            str(config),
            "--release-version",
            "2.0.0",
            "--github-token",
            "secret",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Version: 2.0.0\n")
    assert "Dry run: would" in result.stderr
    assert command(workspace, "show-ref") == before
    assert command(remote, "show-ref") == remote_before
    assert (workspace / "CHANGELOG.md").read_text() == "old\n"
    assert not (workspace / ".git/FETCH_HEAD").exists()
    assert cli_api
    assert all(request.method == "GET" for request in cli_api)


def test_dispatch_creates_pr_against_selected_branch(
    repository: tuple[Path, Path],
    cli_api: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, remote = repository
    command(workspace, "checkout", "-b", "releases/2.0")
    (workspace / "CHANGELOG.md").write_text("release branch notes\n")
    command(workspace, "commit", "-am", "Release branch")
    command(workspace, "push", "origin", "releases/2.0")
    command(workspace, "checkout", "main")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/releases/2.0")
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--release-version",
            "2.0.0",
            "--new-branch",
            "notes",
            "--github-token",
            "secret",
        ],
    )
    assert result.exit_code == 0, result.output
    assert command(remote, "show", "main:CHANGELOG.md") == "old"
    assert (
        command(remote, "show", "releases/2.0:CHANGELOG.md") == "release branch notes"
    )
    content = command(remote, "show", "notes:CHANGELOG.md")
    assert content.startswith("# Version: 2.0.0\n")
    assert content.endswith("release branch notes")
    posts = [request for request in cli_api if request.method == "POST"]
    assert len(posts) == 1
    assert posts[0].url.path == "/repos/o/r/pulls"
    payload = json.loads(posts[0].content)
    assert payload["base"] == "releases/2.0"
    assert payload["head"] == "notes"


def test_empty_run_does_not_create_branch(repository: tuple[Path, Path]) -> None:
    workspace, remote = repository
    posts: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request)
        if request.url.path == "/search/issues":
            return httpx.Response(
                200, json={"total_count": 0, "incomplete_results": False, "items": []}
            )
        return response(request)

    before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        run(
            Settings(
                release_version="v2.0.0",
                github_token=SecretStr("secret"),
                repository="o/r",
                workspace=workspace,
            ),
            github,
            TerminalReporter(),
        )
    assert command(workspace, "show-ref") == before
    assert command(remote, "show-ref") == remote_before
    assert not posts
    assert (workspace / "CHANGELOG.md").read_text() == "old\n"


def test_ambiguous_comment_transport_failure_is_not_swallowed(
    tmp_path: Path, pr_event: Path
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            requests.append(request)
            raise httpx.ReadTimeout("ambiguous", request=request)
        return response(request)

    settings = Settings(
        commit_changelog=False,
        comment_changelog=True,
        github_token=SecretStr("secret"),
        repository="o/r",
        workspace=tmp_path,
    )
    with (
        GitHub(
            "https://api.github.com", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(APIError),
    ):
        run(settings, github, TerminalReporter(), legacy=True)
    assert len(requests) == 1


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_collection_exit_status_boundary(
    legacy: bool,
    status: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pr_event: Path,
) -> None:

    def handle(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(status, text="secret")
            if request.url.path == "/search/issues"
            else response(request)
        )

    def factory(api_url: str, token: str | None = None) -> GitHub:
        return GitHub(api_url, token, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("changelog_ci.cli.GitHub", factory)
    monkeypatch.chdir(tmp_path)
    if legacy:
        monkeypatch.setenv("_CHANGELOG_CI_COMPOSITE", "true")
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--no-commit-changelog",
            "--comment-changelog",
            "--github-token",
            "secret",
        ],
    )
    assert result.exit_code == (0 if legacy and status == 500 else 1), result.output
    assert "secret" not in result.output and "Traceback" not in result.output
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("missing", ["token", "output", "summary"])
def test_missing_mutation_context_fails_before_any_operation(
    missing: str,
    cli_api: list[httpx.Request],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = [
        "actions",
        "--release-version",
        "2.0.0",
    ]
    if missing != "token":
        args += ["--github-token", "secret", "--output-mode", "github"]
    if missing == "summary":
        monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
        args.append("--summary")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2, result.output
    assert {
        "token": "token",
        "output": "GITHUB_OUTPUT",
        "summary": "GITHUB_STEP_SUMMARY",
    }[missing] in result.output
    assert not cli_api and (not list(tmp_path.iterdir()))


@pytest.mark.parametrize("writable", [False, True])
def test_fork_destination_uses_checkout_credentials(
    repository: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writable: bool,
) -> None:
    workspace, remote = repository
    command(workspace, "checkout", "-b", "release")
    command(workspace, "push", "origin", "release")
    command(workspace, "remote", "set-url", "origin", "git@github.com:fork/r.git")
    if not writable:
        monkeypatch.setenv("_CHANGELOG_CI_TEST_DENY_PUSH", "1")
    event = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    event.write_text(
        json.dumps(
            {
                "number": 9,
                "pull_request": {
                    "title": "Release v2.0.0",
                    "head": {"ref": "release", "repo": {"full_name": "fork/r"}},
                    "base": {"ref": "main", "repo": {"full_name": "o/r"}},
                },
            }
        )
    )
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response(request)

    settings = Settings(
        comment_changelog=True,
        github_token=SecretStr("secret"),
        repository="o/r",
        workspace=workspace,
    )
    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        if writable:
            run(settings, github, TerminalReporter())
        else:
            with pytest.raises(GitError, match="push"):
                run(settings, github, TerminalReporter())
    posts = [request for request in requests if request.method == "POST"]
    if writable:
        assert command(remote, "show", "release:CHANGELOG.md").startswith(
            "# Version: v2.0.0"
        )
        assert len(posts) == 1 and posts[0].url.path == "/repos/o/r/issues/9/comments"
    else:
        assert command(remote, "show", "release:CHANGELOG.md") == "old"
        assert not posts
    assert command(remote, "show", "main:CHANGELOG.md") == "old"


@pytest.mark.parametrize("status,legacy", [(422, True), (422, False), (403, True)])
def test_new_pr_failure_status_does_not_retry_or_change_base(
    repository: tuple[Path, Path], status: int, legacy: bool
) -> None:
    workspace, remote = repository
    posts: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(status, text="secret")
        return response(request)

    settings = Settings(
        release_version="2.0.0",
        github_token=SecretStr("secret"),
        repository="o/r",
        workspace=workspace,
        new_branch="notes",
    )
    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        if legacy and status == 422:
            run(settings, github, TerminalReporter(), legacy=legacy)
        else:
            with pytest.raises(APIError):
                run(settings, github, TerminalReporter(), legacy=legacy)
    assert len(posts) == 1
    assert command(remote, "show", "notes:CHANGELOG.md").startswith("# Version: 2.0.0")
    assert command(remote, "show", "main:CHANGELOG.md") == "old"


def test_cli_identity_and_release_patterns_affect_committed_result(
    repository: tuple[Path, Path],
    cli_api: list[httpx.Request],
    pr_event: Path,
) -> None:
    pr_event.write_text(json.dumps(pull_request_event(title="Ship 2026-10-17")))
    workspace, remote = repository
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--pull-request-title-regex",
            "^Ship",
            "--version-regex",
            r"\d{4}-\d{2}-\d{2}",
            "--committer-username",
            "Release Bot",
            "--committer-email",
            "release@example.com",
        ],
    )
    assert result.exit_code == 0, result.output
    assert command(remote, "show", "main:CHANGELOG.md").startswith(
        "# Version: 2026-10-17\n"
    )
    assert (
        command(remote, "log", "-1", "--format=%an <%ae>")
        == "Release Bot <release@example.com>"
    )
    assert all(request.method == "GET" for request in cli_api)


def test_no_pull_request_when_git_filter_leaves_no_changes(
    repository: tuple[Path, Path],
    cli_api: list[httpx.Request],
) -> None:
    workspace, remote = repository
    (workspace / ".gitattributes").write_text("CHANGELOG.md filter=constant\n")
    command(
        workspace,
        "config",
        "filter.constant.clean",
        shlex.join(
            [
                Path(sys.executable).as_posix(),
                "-c",
                (
                    "import sys\n"
                    "sys.stdin.buffer.read()\n"
                    "sys.stdout.buffer.write(b'old\\n')\n"
                ),
            ]
        ),
    )
    command(workspace, "add", ".gitattributes")
    command(workspace, "commit", "-m", "Configure clean filter")
    command(workspace, "push", "origin", "main")
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--release-version",
            "2.0.0",
            "--new-branch",
            "notes",
            "--github-token",
            "secret",
        ],
    )
    assert result.exit_code == 0, result.output
    assert all(request.method == "GET" for request in cli_api)
    assert command(workspace, "branch", "--show-current") == "notes"
    assert (workspace / "CHANGELOG.md").read_text().startswith("# Version: 2.0.0\n")
    assert "refs/heads/notes" not in command(remote, "show-ref", "--heads")
    assert command(remote, "show", "main:CHANGELOG.md") == "old"


def test_non_pr_comment_dry_run_reports_no_mutations(
    cli_api: list[httpx.Request],
    tmp_path: Path,
) -> None:
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--release-version",
            "2.0.0",
            "--no-commit-changelog",
            "--comment-changelog",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "no supported mutations for this event" in result.stderr
    assert "Change 1" in result.stdout
    assert all(request.method == "GET" for request in cli_api)
    assert not list(tmp_path.iterdir())
