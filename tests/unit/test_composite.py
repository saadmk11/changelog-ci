import re
from importlib.metadata import distribution
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, SecretStr
from typer.core import TyperGroup
from typer.main import get_command

from gh_changelog_ci.cli import app
from gh_changelog_ci.config import ACTION_FIELDS, resolve_actions
from gh_changelog_ci.models import Settings
from gh_changelog_ci.reporting import TerminalReporter
from tests.packaging import release

ROOT = Path(__file__).resolve().parents[2]


class Step(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = ""
    run: str = ""
    uses: str = ""
    shell: str = ""
    env: dict[str, str] = {}


class Runs(BaseModel):
    using: str
    steps: list[Step] = []


class Action(BaseModel):
    inputs: dict[str, dict[str, object]]
    outputs: dict[str, dict[str, str]] = {}
    runs: Runs


def test_legacy_defaults_unchanged_and_new_inputs_omitted() -> None:
    old = Action.model_validate(
        yaml.safe_load((ROOT / "tests/fixtures/legacy/action.yaml").read_text())
    )
    new = Action.model_validate(yaml.safe_load((ROOT / "action.yaml").read_text()))
    for name, value in old.inputs.items():
        assert new.inputs[name].get("default") == value.get("default")
        assert new.inputs[name].get("required") == value.get("required")
    for name in new.inputs.keys() - old.inputs.keys():
        assert "default" not in new.inputs[name]
    env = {
        f"INPUT_{name.upper()}": str(value.get("default", ""))
        for name, value in new.inputs.items()
    }
    env["INPUT_GITHUB_TOKEN"] = "test-token"
    env["GITHUB_ACTIONS"] = "true"
    assert resolve_actions({}, env, TerminalReporter()) == Settings(
        github_token=SecretStr("test-token")
    )


def test_composite_maps_every_input_and_output_without_shell_interpolation() -> None:
    action = Action.model_validate(yaml.safe_load((ROOT / "action.yaml").read_text()))
    assert action.inputs.keys() == ACTION_FIELDS | {"config_file"}
    assert action.runs.using == "composite"
    invoke = next(step for step in action.runs.steps if step.id == "changelog")
    for name in action.inputs:
        assert invoke.env[f"INPUT_{name.upper()}"] == "${{ inputs." + name + " }}"
    for name, value in action.outputs.items():
        assert value["value"] == "${{ steps.changelog.outputs." + name + " }}"
    assert set(action.outputs) == {
        "changelog",
        "changed",
        "changelog-file",
        "pull-request-number",
        "pull-request-url",
    }
    assert "${{" not in invoke.run
    assert "--github-token" not in invoke.run
    assert "--no-config tool run --isolated --no-env-file" in invoke.run
    assert "--default-index https://pypi.org/simple" in invoke.run
    assert "unset PYTHONPATH PYTHONHOME VIRTUAL_ENV" in invoke.run
    assert "${!UV_@}" in invoke.run and "${!PIP_@}" in invoke.run
    assert "--python 3.15" in invoke.run
    for step in action.runs.steps:
        if step.run:
            assert step.shell == "bash"
        if step.uses:
            assert re.search(r"@[0-9a-f]{40}$", step.uses)


def test_cli_shared_option_declarations_cannot_drift() -> None:
    command = get_command(app)
    assert isinstance(command, TyperGroup)
    commands = command.commands
    generate = {p.name: p for p in commands["generate"].params}
    actions = {p.name: p for p in commands["actions"].params}
    for name in generate.keys() & actions.keys():
        parameter = generate[name]
        assert parameter.opts == actions[name].opts
        assert parameter.default == actions[name].default
    assert {"repository", "api_url", "workspace", "stdout"}.isdisjoint(actions)
    assert {
        "committer_username",
        "committer_email",
        "pull_request_title_regex",
        "version_regex",
        "commit_changelog",
        "comment_changelog",
    }.isdisjoint(generate)
    assert {
        "event_name",
        "event_path",
        "pull_request_number",
        "pull_request_title",
        "head_branch",
        "base_branch",
    }.isdisjoint(Settings.model_fields.keys() | generate.keys() | actions.keys())


def test_release_metadata_is_consistent() -> None:
    package = distribution("gh-changelog-ci")
    expected = package.version
    assert release.validate_release(f"v{expected}") == expected
    assert {
        entry.name: entry.value
        for entry in package.entry_points
        if entry.group == "console_scripts"
    } == {"gh-changelog-ci": "gh_changelog_ci.cli:app"}


@pytest.mark.parametrize(
    "tag,package_version,action_version",
    (
        pytest.param("2.0.0", "2.0.0", "2.0.0", id="missing-tag-prefix"),
        pytest.param("vv2.0.0", "2.0.0", "2.0.0", id="duplicate-tag-prefix"),
        pytest.param("v2.0.0\n", "2.0.0", "2.0.0", id="multiline-tag"),
        pytest.param("v2.0.1", "2.0.0", "2.0.0", id="mismatched-tag"),
        pytest.param("v2.0.0", "v2.0.0", "2.0.0", id="prefixed-package-version"),
        pytest.param("v2.0.0", "2.0.0", "v2.0.0", id="prefixed-action-version"),
        pytest.param("v2.0.0", "2.0.0", "2.0.1", id="mismatched-action-version"),
    ),
)
def test_invalid_release_metadata(
    tag: str,
    package_version: str,
    action_version: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release, "__file__", str(tmp_path / "tests/packaging/release.py")
    )
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nversion = "{package_version}"\n'
    )
    (tmp_path / "action.yaml").write_text(
        f"runs:\n  steps:\n    - run: gh-changelog-ci[actions]=={action_version}\n"
    )
    with pytest.raises(ValueError):
        release.validate_release(tag)
