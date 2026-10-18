import importlib.util
import re
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from gh_changelog_ci.cli import app
from gh_changelog_ci.errors import ChangelogError, ConfigurationError

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
def test_diagnostics_redact_secrets_and_escape_commands(
    capsys: pytest.CaptureFixture[str], level: str
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    reporter = GitHubReporter("secret")
    capsys.readouterr()
    getattr(reporter, level)("secret\n::error::injected")
    assert capsys.readouterr().out == f"::{level} ::***%0A::error::injected\n"


def test_preview_redacts_secrets_and_resumes_workflow_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    reporter = GitHubReporter("secret")
    capsys.readouterr()
    reporter.content("::warning::content\nsecret")
    output = capsys.readouterr().out
    assert re.fullmatch(
        r"::group ::Changelog preview\n"
        r"::stop-commands::(?P<token>[0-9a-f]{32})\n"
        r"::warning::content\n\*\*\*\n"
        r"::(?P=token)::\n"
        r"::endgroup::\n",
        output,
    )


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


def test_reporter_requires_runner_before_masking(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gh_changelog_ci.actions.reporting import GitHubReporter

    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(ConfigurationError, match="requires a GitHub Actions runner"):
        GitHubReporter("secret")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "operation", ["notice", "warning", "error", "content", "outputs"]
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
        if operation == "outputs":
            reporter.outputs({"changelog": "section"})
        else:
            getattr(reporter, operation)("message")
    assert capsys.readouterr().out == ""
    assert not list(tmp_path.iterdir())
