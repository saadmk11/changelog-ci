import importlib.util
import json
import re
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from gh_changelog_ci.cli import app
from gh_changelog_ci.errors import ChangelogError, ConfigurationError
from tests.git import command

pytestmark = [
    pytest.mark.actions,
    pytest.mark.skipif(
        importlib.util.find_spec("github_action_utils") is None,
        reason="actions extra required",
    ),
]


@pytest.mark.parametrize("legacy", [False, True])
def test_multiline_output_unicode_delimiters_and_commands(
    legacy: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    path = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    value = "::warning::literal\n__ENV_DELIMITER__\nUnicode 🐛\r\n100%\n"
    GitHubReporter().outputs({"changelog": value}, legacy=legacy)
    content = path.read_text(encoding="utf-8")
    header, *body, delimiter = content.splitlines()
    assert header == f"changelog<<{delimiter}"
    assert delimiter not in body
    if legacy:
        assert body == [
            "::warning::literal%0A__ENV_DELIMITER__%0AUnicode 🐛%0D%0A100%25%0A"
        ]
    else:
        assert body == [
            "::warning::literal",
            "__ENV_DELIMITER__",
            "Unicode 🐛",
            "100%",
            "",
        ]


@pytest.mark.parametrize("level", ["notice", "warning", "error"])
@pytest.mark.parametrize("quiet", [False, True])
def test_diagnostics_escape_commands(
    capsys: pytest.CaptureFixture[str], level: str, quiet: bool
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    reporter = GitHubReporter(quiet=quiet)
    getattr(reporter, level)("message\n::error::injected")
    assert capsys.readouterr().out == (
        ""
        if quiet and level == "notice"
        else f"::{level} ::message%0A::error::injected\n"
    )


def test_preview_preserves_content_and_resumes_workflow_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    reporter = GitHubReporter()
    reporter.content("::warning::content\noriginal")
    output = capsys.readouterr().out
    assert re.fullmatch(
        r"::group ::Changelog preview\n"
        r"::stop-commands::(?P<token>[0-9a-f]{32})\n"
        r"::warning::content\noriginal\n"
        r"::(?P=token)::\n"
        r"::endgroup::\n",
        output,
    )


@pytest.mark.parametrize("quiet", [False, True])
def test_progress_groups_escape_titles_and_close_on_failure(
    quiet: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    reporter = GitHubReporter(quiet=quiet)
    with pytest.raises(RuntimeError), reporter.group("title\n::error::injected"):
        reporter.notice("Working.")
        raise RuntimeError
    output = capsys.readouterr().out
    assert output == (
        ""
        if quiet
        else "::group ::title%0A::error::injected\n::notice ::Working.\n::endgroup::\n"
    )


@pytest.mark.parametrize("mode", ["default", "quiet", "verbose"])
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_successful_action_reports_progress_preview_and_results(
    mode: str,
    event: str,
    pr_event: Path,
    repository: tuple[Path, Path],
    cli_api: list[httpx.Request],
    cli_changes: list[dict[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, remote = repository
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    cli_changes[0]["title"] = "Fix secret\n::error::injected"
    for key, value in {
        "GITHUB_EVENT_NAME": event,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "_CHANGELOG_CI_COMPOSITE": "true",
    }.items():
        monkeypatch.setenv(key, value)
    args = [
        "actions",
        "--output-mode",
        "github",
        "--github-token",
        "secret",
        "--summary",
    ]
    if event == "pull_request":
        branch = "main"
        args.append("--comment-changelog")
    else:
        branch = "release-notes"
        args += ["--release-version", "v2.0.2", "--new-branch", branch]
    if mode != "default":
        args.append(f"--{mode}")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.stderr == "::add-mask::secret\n"
    assert result.output.startswith("::add-mask::secret\n")
    log = result.stdout
    expected = (
        "# Version: v2.0.2\n\n"
        "* [#1](https://github.com/o/r/pull/1): Fix secret\n::error::injected\n"
    )
    assert summary.read_text() == expected
    assert command(remote, "show", f"{branch}:CHANGELOG.md", strip=False) == (
        expected + "\n\nold\n"
    )
    content = output.read_text()
    header = content.splitlines()[0]
    delimiter = header.removeprefix("changelog<<")
    assert content.startswith(
        f"{header}\n# Version: v2.0.2%0A%0A"
        "* [#1](https://github.com/o/r/pull/1): Fix secret%0A::error::injected%0A\n"
        f"{delimiter}\n"
    )
    assert ("Fix secret" in log) == (mode == "verbose")
    assert [
        json.loads(request.content)["body"]
        for request in cli_api
        if request.method == "POST"
    ] == [expected]
    posts = [request.url.path for request in cli_api if request.method == "POST"]
    if event == "pull_request":
        assert posts == ["/repos/o/r/issues/9/comments"]
        success = "Changelog comment added to pull request #9."
    else:
        assert posts == ["/repos/o/r/pulls"]
        success = "Pull request opened at https://github.com/o/r/pull/9."
    if mode == "quiet":
        assert log == ""
    else:
        assert "::group ::Generate changelog\n" in log
        assert "Generating changelog for version v2.0.2." in log
        assert "::group ::Commit and push changelog\n" in log
        assert "Changelog committed and pushed." in log
        details = [
            "Collecting pull_request changes.",
            "Repository: o/r.",
            "Collected 1 change.",
            "::group ::Prepare changelog branch\n",
            "Commit author:",
            "Changelog file: CHANGELOG.md.",
            f"Push branch: {branch}.",
            "Updating CHANGELOG.md.",
            "::group ::Changelog preview\n",
        ]
        details += (
            [
                "Checking out pull request branch main.",
                "Adding changelog to pull request",
            ]
            if event == "pull_request"
            else [
                f"Creating branch {branch} from main.",
                f"Opening a pull request from {branch} to main.",
            ]
        )
        for detail in details:
            assert (detail in log) == (mode == "verbose"), detail
        assert success in log
        assert log.endswith("::notice ::Changelog CI complete.\n")
        assert log.count("::group ") == log.count("::endgroup::")
        if mode == "verbose":
            assert re.search(
                r"::stop-commands::([0-9a-f]{32})\n"
                + re.escape(expected)
                + r"\n::\1::\n",
                log,
            )


def test_failed_comment_closes_progress_group_without_success_message(
    pr_event: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gh_changelog_ci.github import GitHub
    from tests.github import response

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(403)
        return response(request)

    def factory(api_url: str, token: SecretStr | None = None) -> GitHub:
        return GitHub(api_url, token, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("gh_changelog_ci.cli.GitHub", factory)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    result = CliRunner().invoke(
        app,
        [
            "actions",
            "--output-mode",
            "github",
            "--github-token",
            "secret",
            "--no-commit-changelog",
            "--comment-changelog",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "Changelog comment added" not in result.stdout
    assert "Changelog CI complete." not in result.stdout
    assert result.stdout.count("::group ") == result.stdout.count("::endgroup::")
    assert "::endgroup::\n::error ::" in result.stdout
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("preview", ["--dry-run", "--diff"])
@pytest.mark.parametrize("mode", ["default", "quiet", "verbose"])
def test_action_prints_only_one_explicit_preview(
    preview: str,
    mode: str,
    pr_event: Path,
    cli_api: list[httpx.Request],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    args = [
        "actions",
        "--output-mode",
        "github",
        "--github-token",
        "secret",
        "--no-commit-changelog",
        "--comment-changelog",
        preview,
    ]
    if mode != "default":
        args.append(f"--{mode}")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.stdout.count("::group ::Changelog preview\n") == 1
    assert result.stdout.count("Change 1") == 1
    if mode == "quiet":
        assert "::notice" not in result.stdout
    assert ("Changelog CI complete." in result.stdout) == (
        preview == "--diff" and mode != "quiet"
    )
    assert not (tmp_path / "CHANGELOG.md").exists()
    assert sum(request.method == "POST" for request in cli_api) == (preview == "--diff")


@pytest.mark.parametrize(
    "value,legacy",
    [
        pytest.param("x" * 524289, False, id="raw"),
        pytest.param("\n" * 200000, True, id="escaped"),
    ],
)
def test_output_limit_is_checked_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, legacy: bool
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with pytest.raises(ChangelogError, match="output limit"):
        GitHubReporter().outputs({"changelog": value}, legacy=legacy)
    assert not output.exists()


def test_summary_limit_warns_without_losing_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    output = tmp_path / "output"
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    reporter = GitHubReporter()
    reporter.outputs({"changelog": "section"}, summary="x" * 1048577)
    header, value, delimiter = output.read_text().splitlines()
    assert header == f"changelog<<{delimiter}"
    assert value == "section"
    assert not summary.exists()
    assert "Summary omitted" in capsys.readouterr().out
    reporter.outputs({}, summary="# Summary\n")
    assert summary.read_text() == "# Summary\n"


def test_missing_output_file_environment() -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    with pytest.raises(ChangelogError, match="GITHUB_OUTPUT"):
        GitHubReporter().outputs({"changed": "false"})


def test_generate_writes_github_outputs_and_summary_only_on_runner(
    cli_api: list[httpx.Request], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
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
            "--verbose",
        ],
    )
    expected = "# Version: 1\n\n* [#1](https://github.com/o/r/pull/1): Change 1\n"
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "::notice ::Collecting pull_request changes.\n::notice ::Changelog updated.\n"
    )
    assert result.stderr == ""
    assert (tmp_path / "CHANGELOG.md").read_text() == expected
    assert summary.read_text() == expected
    content = output.read_text()
    header = content.splitlines()[0]
    delimiter = header.removeprefix("changelog<<")
    assert re.fullmatch("[0-9a-f]{32}", delimiter)
    assert content.startswith(f"{header}\n{expected}\n{delimiter}\n")
    assert [(request.method, request.url.path) for request in cli_api] == [
        ("GET", "/repos/o/r/releases/latest"),
        ("GET", "/search/issues"),
    ]


def test_legacy_escaping_applies_only_to_changelog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    GitHubReporter().outputs(
        {"changelog": "100%\n", "changelog-file": "100% complete.md"}, legacy=True
    )
    content = output.read_text()
    assert "100%25%0A" in content
    assert "100% complete.md" in content


def test_reporter_requires_runner(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(ConfigurationError, match="requires a GitHub Actions runner"):
        GitHubReporter()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "operation", ["group", "notice", "warning", "error", "content", "outputs"]
)
def test_reporter_cannot_be_reused_outside_runner(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    reporter = GitHubReporter()
    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(ConfigurationError, match="requires a GitHub Actions runner"):
        if operation == "group":
            with reporter.group("message"):
                pytest.fail("Group entered outside a runner")
        elif operation == "outputs":
            reporter.outputs({"changelog": "section"})
        else:
            getattr(reporter, operation)("message")
    assert capsys.readouterr().out == ""
    assert not list(tmp_path.iterdir())
