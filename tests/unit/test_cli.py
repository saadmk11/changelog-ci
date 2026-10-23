import importlib.util
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from gh_changelog_ci.cli import app
from gh_changelog_ci.github import GitHub
from tests.github import linked_issues, pull_request, response

runner = CliRunner()


@pytest.mark.parametrize("grouped", [False, True])
def test_existing_label_configuration_needs_no_token_or_graphql(
    grouped: bool,
    cli_changes: list[dict[str, object]],
    cli_api: list[httpx.Request],
    tmp_path: Path,
) -> None:
    cli_changes[:] = [
        pull_request(1, labels=("bug",)),
        pull_request(2, labels=("skip",)),
        pull_request(3, labels=("docs",)),
    ]
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "group_config": [{"title": "Fixes", "labels": ["bug"]}]
                if grouped
                else [],
                "exclude_labels": ["skip"],
            }
        )
    )
    result = runner.invoke(
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
    first = "* [#1](https://github.com/o/r/pull/1): Change 1\n"
    third = "* [#3](https://github.com/o/r/pull/3): Change 3\n"
    expected = (
        f"\n#### Fixes\n\n{first}\n#### Other Changes\n\n{third}"
        if grouped
        else first + third
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == f"# Version: 1\n\n{expected}"
    assert [(r.method, r.url.path) for r in cli_api] == [
        ("GET", "/repos/o/r/releases/latest"),
        ("GET", "/search/issues"),
    ]
    assert all("Authorization" not in r.headers for r in cli_api)


def test_issue_type_grouping_does_not_query_excluded_pull_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/graphql":
            number = json.loads(request.content)["variables"]["number"]
            return httpx.Response(
                403 if number == 2 else 200, json=linked_issues("Bug")
            )
        return response(
            request,
            changes=[pull_request(1), pull_request(2, labels=("skip",))],
        )

    def factory(api_url: str, token: SecretStr | None = None) -> GitHub:
        return GitHub(api_url, token, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("gh_changelog_ci.cli.GitHub", factory)
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--github-token",
            "secret",
            "--stdout",
            "--group-by",
            "issue_type",
            "--group-config",
            '{"title":"Fixes","issue_types":["Bug"]}',
            "--exclude-label",
            "skip",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "# Version: 1\n\n\n#### Fixes\n\n"
        "* [#1](https://github.com/o/r/pull/1): Change 1\n"
    )
    assert [
        json.loads(r.content)["variables"]["number"]
        for r in requests
        if r.url.path == "/graphql"
    ] == [1]


@pytest.mark.parametrize("graphql_error", [False, True])
def test_cli_groups_by_linked_issue_types(
    graphql_error: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/graphql":
            if graphql_error:
                return httpx.Response(200, json={"errors": [{"message": "secret"}]})
            return httpx.Response(200, json=linked_issues("Bug"))
        return response(request, changes=[pull_request(labels=("feature",))])

    def factory(api_url: str, token: SecretStr | None = None) -> GitHub:
        return GitHub(api_url, token, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("gh_changelog_ci.cli.GitHub", factory)
    path = tmp_path / "CHANGELOG.md"
    path.write_text("Existing changelog\n")
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--workspace",
            str(tmp_path),
            "--github-token",
            "secret",
            "--group-by",
            "issue_type",
            "--group-config",
            '{"title":"Fixes","issue_types":["Bug"]}',
        ],
    )
    if graphql_error:
        assert result.exit_code == 1, result.output
        assert "could not read linked issue types" in result.stderr
        assert "secret" not in result.output
        assert path.read_text() == "Existing changelog\n"
    else:
        assert result.exit_code == 0, result.output
        assert path.read_text() == (
            "# Version: 1\n\n\n#### Fixes\n\n"
            "* [#1](https://github.com/o/r/pull/1): Change 1\n\n\n"
            "Existing changelog\n"
        )
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/repos/o/r/releases/latest"),
        ("GET", "/search/issues"),
        ("POST", "/graphql"),
    ]


@pytest.mark.parametrize("commit_source", [False, True])
def test_issue_type_lookup_is_skipped_without_pr_grouping(
    commit_source: bool, cli_api: list[httpx.Request]
) -> None:
    extra = (
        [
            "--changelog-type",
            "commit_message",
            "--group-config",
            '{"title":"Fixes","issue_types":["Bug"]}',
        ]
        if commit_source
        else []
    )
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--stdout",
            "--group-by",
            "issue_type",
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    entry = (
        "* [abcdef0](https://github.com/o/r/commit/abcdef01234): Fix a bug\n"
        if commit_source
        else "* [#1](https://github.com/o/r/pull/1): Change 1\n"
    )
    assert result.stdout == f"# Version: 1\n\n{entry}"
    assert [(r.method, r.url.path) for r in cli_api] == [
        ("GET", "/repos/o/r/releases/latest"),
        ("GET", "/repos/o/r/commits" if commit_source else "/search/issues"),
    ]


@pytest.mark.parametrize(
    "args,expected",
    [
        pytest.param([], ("generate", "actions", "--version"), id="root"),
        pytest.param(["generate"], ("--repository", "--stdout"), id="generate"),
        pytest.param(
            ["actions"], ("--comment-changelog", "--create-pull-request"), id="actions"
        ),
    ],
)
def test_help(args: list[str], expected: tuple[str, ...]) -> None:
    result = runner.invoke(app, [*args, "--help"], env={"COLUMNS": "120"})
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.stdout
    for text in expected:
        assert text in result.stdout
    assert result.stderr == ""


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.stdout == f"{version('gh-changelog-ci')}\n"
    assert result.stderr == ""


def test_python_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "gh_changelog_ci", "--version"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == version("gh-changelog-ci")


def test_stdout_and_no_workflow_environment(
    cli_api: list[httpx.Request], tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "date-label",
            "--stdout",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (
        result.stdout
        == "# Version: date-label\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    )
    assert result.stderr == ""
    assert not list(tmp_path.iterdir())
    assert all(request.method == "GET" for request in cli_api)


@pytest.mark.parametrize("mode", ["--dry-run", "--stdout"])
def test_preview_does_not_write(
    mode: str, cli_api: list[httpx.Request], tmp_path: Path
) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("old")
    result = runner.invoke(
        app, ["generate", "--repository", "o/r", "--release-version", "1", mode]
    )
    assert result.exit_code == 0, result.output
    assert path.read_text() == "old"
    assert result.stdout == (
        "# Version: 1\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    )
    assert [(request.method, request.url.path) for request in cli_api] == [
        ("GET", "/repos/o/r/releases/latest"),
        ("GET", "/search/issues"),
    ]


def test_default_file_write_rerun_and_diff(
    cli_api: list[httpx.Request], tmp_path: Path
) -> None:
    args = ["generate", "--repository", "o/r", "--release-version", "1"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    path = tmp_path / "CHANGELOG.md"
    once = "# Version: 1\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    assert path.read_text() == once
    result = runner.invoke(app, [*args, "--dry-run", "--diff"])
    assert result.exit_code == 0 and "+# Version: 1" in result.stdout
    assert path.read_text() == once
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert path.read_text() == once + "\n\n" + once


def test_empty_generation_keeps_file_and_reports_no_changes(
    cli_api: list[httpx.Request],
    cli_changes: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    cli_changes.clear()
    path = tmp_path / "CHANGELOG.md"
    path.write_bytes(b"existing\r\n")
    result = runner.invoke(
        app, ["generate", "--repository", "o/r", "--release-version", "1"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert result.stderr == "No changes found.\n"
    assert path.read_bytes() == b"existing\r\n"
    assert len(cli_api) == 2


def test_diff_of_non_utf8_file_is_clean_error_without_writes(
    cli_api: list[httpx.Request], tmp_path: Path
) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_bytes(b"\xffexisting\n")
    result = runner.invoke(
        app, ["generate", "--repository", "o/r", "--release-version", "1", "--diff"]
    )
    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert "Filesystem operation failed" in result.stderr
    assert "Traceback" not in result.output
    assert path.read_bytes() == b"\xffexisting\n"
    assert len(cli_api) == 2


@pytest.mark.parametrize(
    "option,diagnostics",
    [
        ("--quiet", ""),
        ("--verbose", "Collecting pull_request changes.\nChangelog updated.\n"),
    ],
)
def test_progress_options_do_not_change_generated_content(
    option: str, diagnostics: str, cli_api: list[httpx.Request], tmp_path: Path
) -> None:
    result = runner.invoke(
        app, ["generate", "--repository", "o/r", "--release-version", "1", option]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert result.stderr == diagnostics
    assert (tmp_path / "CHANGELOG.md").read_text() == (
        "# Version: 1\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    )


@pytest.mark.parametrize(
    "extra,expected",
    [
        (
            ["--header-prefix", "Release:"],
            "# Release: 1\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n",
        ),
        (
            ["--changelog-type", "commit_message"],
            "# Version: 1\n\n"
            "* [abcdef0](https://github.com/o/r/commit/abcdef01234): Fix a bug\n",
        ),
        (
            ["--changelog-filename", "out.rst"],
            "Version: 1\n==========\n\n"
            "* `#1 <https://github.com/o/r/pull/1>`__: Change 1\n",
        ),
        (
            [
                "--group-config",
                '{"title":"Fixes","labels":["bug"]}',
                "--unlabeled-group-title",
                "Unmatched",
            ],
            "# Version: 1\n\n\n#### Unmatched\n\n"
            "* [#1](https://github.com/o/r/pull/1): Change 1\n",
        ),
        (
            [
                "--group-config",
                '{"title":"Fixes","labels":["bug"]}',
                "--no-include-unlabeled-changes",
            ],
            "# Version: 1\n\n",
        ),
    ],
    ids=(
        "header-prefix",
        "commit-source",
        "rst",
        "unlabeled-title",
        "exclude-unlabeled",
    ),
)
def test_generation_option_effects(
    extra: list[str], expected: str, cli_api: list[httpx.Request]
) -> None:
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--stdout",
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == expected


def test_repeated_exclude_labels_filter_matching_changes(
    cli_api: list[httpx.Request], cli_changes: list[dict[str, object]]
) -> None:
    cli_changes[:] = [
        pull_request(1, labels=("bug",)),
        pull_request(2, labels=("docs",)),
        pull_request(3),
    ]
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--stdout",
            "--exclude-label",
            "bug",
            "--exclude-label",
            "docs",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "# Version: 1\n\n* [#3](https://github.com/o/r/pull/3): Change 3\n"
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--clear-groups", "--group-config", "{}"],
        ["--clear-exclude-labels", "--exclude-label", "bug"],
        ["--group-config", "invalid"],
        ["--stdout", "--summary"],
        ["--stdout", "--output-mode", "github"],
        ["--stdout", "--diff"],
        ["--verbose", "--quiet"],
        ["--summary"],
        ["--changelog-type", "unknown"],
    ],
)
def test_conflicts_and_invalid_options(
    args: list[str], cli_api: list[httpx.Request]
) -> None:
    result = runner.invoke(
        app, ["generate", "--repository", "o/r", "--release-version", "1", *args]
    )
    assert result.exit_code == 2, result.output
    assert not cli_api
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "extra,expected",
    [
        pytest.param(
            ["--group-config", '{"title":"Replacement","labels":["bug"]}'],
            "# Version: 1\n\n\n#### Replacement\n\n"
            "* [#1](https://github.com/o/r/pull/1): Change 1\n",
            id="replace-groups",
        ),
        pytest.param(
            ["--clear-groups"],
            "# Version: 1\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n",
            id="clear-groups",
        ),
        pytest.param(
            ["--exclude-label", "bug"],
            "# Version: 1\n\n\n#### Configured\n\n"
            "* [#2](https://github.com/o/r/pull/2): Change 2\n",
            id="replace-exclusions",
        ),
        pytest.param(
            ["--clear-exclude-labels"],
            "# Version: 1\n\n\n#### Configured\n\n"
            "* [#1](https://github.com/o/r/pull/1): Change 1\n"
            "* [#2](https://github.com/o/r/pull/2): Change 2\n",
            id="clear-exclusions",
        ),
    ],
)
def test_lists_replace_and_clear_config(
    extra: list[str],
    expected: str,
    cli_api: list[httpx.Request],
    cli_changes: list[dict[str, object]],
    tmp_path: Path,
) -> None:
    cli_changes[:] = [
        pull_request(1, labels=("bug",)),
        pull_request(2, labels=("docs",)),
    ]
    config = tmp_path / "c.json"
    config.write_text(
        json.dumps(
            {
                "group_config": [{"title": "Configured", "labels": ["bug", "docs"]}],
                "include_unlabeled_changes": False,
                "exclude_labels": ["docs"],
            }
        )
    )
    result = runner.invoke(
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
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == expected


def test_missing_repository() -> None:
    result = runner.invoke(app, ["generate"])
    assert result.exit_code == 2, result.output
    assert "--repository" in result.output


def test_missing_actions_dependency_does_not_prevent_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    result = runner.invoke(app, ["actions"])
    assert result.exit_code == 2 and "gh-changelog-ci[actions]" in result.output
    help_result = runner.invoke(app, ["actions", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "--comment-changelog" in help_result.stdout


def test_api_failure_exit_and_token_redaction(
    cli_api: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gh_changelog_ci.github import GitHub

    def fail(self: GitHub, repository: str) -> None:
        from gh_changelog_ci.errors import APIError

        raise APIError("read", 403)

    monkeypatch.setattr(GitHub, "latest_release", fail)
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--github-token",
            "top-secret",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "403" in result.output
    assert "top-secret" not in result.output and "Traceback" not in result.output


def test_environment_token_and_enterprise_url(
    cli_api: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHANGELOG_CI_GITHUB_TOKEN", "secret")
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--api-url",
            "https://ghe.example/api/v3",
            "--stdout",
        ],
    )
    assert result.exit_code == 0
    assert cli_api[0].headers["Authorization"] == "Bearer secret"
    assert cli_api[0].url.host == "ghe.example"
    assert cli_api[0].url.path == "/api/v3/repos/o/r/releases/latest"


def test_cli_passes_wrapped_token_to_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens: list[SecretStr | None] = []

    def factory(api_url: str, token: SecretStr | None = None) -> GitHub:
        tokens.append(token)
        return GitHub(api_url, token, transport=httpx.MockTransport(response))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("gh_changelog_ci.cli.GitHub", factory)
    result = runner.invoke(
        app,
        [
            "generate",
            "--repository",
            "o/r",
            "--release-version",
            "1",
            "--github-token",
            "test-sensitive-token",
            "--stdout",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(tokens) == 1
    assert isinstance(tokens[0], SecretStr)
    assert tokens[0].get_secret_value() == "test-sensitive-token"
