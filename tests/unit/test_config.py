import json
from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from gh_changelog_ci.config import (
    LEGACY_FIELDS,
    legacy_settings,
    resolve_actions,
    resolve_standalone,
)
from gh_changelog_ci.errors import ConfigurationError
from gh_changelog_ci.models import Group, GroupBy, Settings
from gh_changelog_ci.reporting import TerminalReporter


class LegacyConfig(BaseModel):
    input: dict[str, object]
    expected: dict[str, object]


LEGACY_CONFIGS = TypeAdapter(list[LegacyConfig]).validate_json(
    (Path(__file__).parents[1] / "fixtures/legacy/config.json").read_bytes()
)


@pytest.mark.parametrize("case", LEGACY_CONFIGS)
def test_recorded_legacy_configuration(case: LegacyConfig) -> None:
    expected = dict(case.expected)
    for key in ("committer_username", "committer_email"):
        expected[key] = expected.pop("git_" + key)
    # Extra group keys and non-string exclusions do not affect matching.
    groups = expected["group_config"]
    assert isinstance(groups, list)
    expected["group_config"] = [
        {
            **{
                key: value for key, value in group.items() if key in {"title", "labels"}
            },
            "issue_types": [],
        }
        for group in groups
    ]
    labels = expected["exclude_labels"]
    assert isinstance(labels, list)
    expected["exclude_labels"] = [label for label in labels if isinstance(label, str)]
    assert (
        legacy_settings(case.input, TerminalReporter()).model_dump(
            mode="json", include=set(LEGACY_FIELDS)
        )
        == expected
    )


def test_explicit_empty_environment_overrides_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"header_prefix": "File:"}')
    settings = resolve_standalone(
        {"config_file": path}, {"CHANGELOG_CI_HEADER_PREFIX": ""}
    )
    assert settings.header_prefix == ""


def test_defaults() -> None:
    settings = Settings()
    assert settings.commit_changelog and not settings.comment_changelog
    assert settings.changelog_filename == "CHANGELOG.md"
    assert settings.header_prefix == "Version:"
    assert settings.committer_username == "github-actions[bot]"
    assert settings.committer_email == "github-actions[bot]@users.noreply.github.com"
    assert settings.github_token is None
    assert settings.group_by == GroupBy.LABELS


@pytest.mark.parametrize(
    "key,value",
    [
        ("commit_changelog", "false"),
        ("comment_changelog", 0),
        ("include_unlabeled_changes", 1),
        ("version_regex", "["),
        ("pull_request_title_regex", 3),
        ("changelog_filename", "bad.txt"),
        ("group_config", [{}]),
        ("group_by", "invalid"),
        ("group_config", [{"title": "Fixes"}]),
        ("group_config", [{"title": "Fixes", "issue_types": []}]),
        ("group_config", [{"title": "Fixes", "issue_types": [1]}]),
        ("group_config", [{"title": "Fixes", "labels": [1]}]),
        ("exclude_labels", [1]),
        ("unknown", "token-secret"),
        ("github_token", 5),
        ("release_version", "line\nbreak"),
        ("commit_message", "message\0invalid"),
    ],
)
def test_strict_config_rejects_invalid_values(
    key: str, value: object, tmp_path: Path
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({key: value}))
    with pytest.raises(ConfigurationError) as error:
        resolve_standalone({"config_file": config}, {})
    assert "token-secret" not in str(error.value)


@pytest.mark.parametrize(
    "extension,content",
    [
        ("json", '{"header_prefix":"File","comment_changelog":true}'),
        ("yaml", "header_prefix: File\ncomment_changelog: true\n"),
        ("yml", "header_prefix: File\ncomment_changelog: true\n"),
    ],
)
def test_precedence(
    extension: str, content: str, tmp_path: Path, runner_env: dict[str, str]
) -> None:
    config = tmp_path / f"settings.{extension}"
    config.write_text(content)
    settings = resolve_standalone(
        {"config_file": config, "header_prefix": "CLI", "comment_changelog": False},
        {"CHANGELOG_CI_HEADER_PREFIX": "Env"},
    )
    assert settings.header_prefix == "CLI" and not settings.comment_changelog
    settings = resolve_standalone(
        {"config_file": config}, {"CHANGELOG_CI_HEADER_PREFIX": "Env"}
    )
    assert settings.header_prefix == "Env" and settings.comment_changelog
    settings = resolve_actions(
        {"config_file": config, "header_prefix": "New input"},
        {**runner_env, "CHANGELOG_CI_HEADER_PREFIX": "ignored"},
        TerminalReporter(),
    )
    assert settings.header_prefix == "New input" and settings.comment_changelog


def test_legacy_file_over_six_inputs_and_aliases(
    tmp_path: Path, runner_env: dict[str, str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "changelog_filename": "FILE.rst",
                "git_committer_username": "File author",
                "git_committer_email": "file@example.com",
                "release_version": "file",
                "github_token": "file-token",
            }
        )
    )
    settings = resolve_actions(
        {
            "config_file": config,
            "changelog_filename": "CLI.md",
            "release_version": "cli",
            "committer_username": "CLI",
        },
        {
            **runner_env,
            "INPUT_GITHUB_TOKEN": "input-token",
            "CHANGELOG_CI_RELEASE_VERSION": "ignored",
        },
        TerminalReporter(),
    )
    assert settings.changelog_filename == "FILE.rst"
    assert settings.committer_username == "File author"
    assert settings.committer_email == "file@example.com"
    assert settings.release_version == "file"
    assert (
        settings.github_token
        and settings.github_token.get_secret_value() == "file-token"
    )


def test_toml_is_workspace_only_and_not_action_implicit(
    tmp_path: Path, runner_env: dict[str, str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.changelog-ci]\nheader_prefix="TOML"\n'
    )
    settings = resolve_standalone({"workspace": tmp_path}, {})
    assert settings.header_prefix == "TOML"
    nested = tmp_path / "nested"
    nested.mkdir()
    settings = resolve_standalone({"workspace": nested}, {})
    assert settings.header_prefix == "Version:"
    settings = resolve_actions(
        {}, {**runner_env, "GITHUB_WORKSPACE": str(tmp_path)}, TerminalReporter()
    )
    assert settings.header_prefix == "Version:"


@pytest.mark.parametrize(
    "content", ["[]", "null", "{", "!!python/object/apply:builtins.open []"]
)
def test_invalid_and_unsafe_files(
    content: str, tmp_path: Path, runner_env: dict[str, str]
) -> None:
    path = tmp_path / "config.yaml"
    if content.startswith("!!python/object/apply"):
        content = "!!python/object/apply:builtins.open " + json.dumps(
            [str(tmp_path / "injected"), "w"]
        )
    path.write_text(content)
    with pytest.raises(ConfigurationError):
        resolve_standalone({"config_file": path}, {})
    settings = resolve_actions({"config_file": path}, runner_env, TerminalReporter())
    assert settings == Settings()
    assert not (tmp_path / "injected").exists()


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="missing file"):
        resolve_standalone({"config_file": tmp_path / "missing.json"}, {})


@pytest.mark.parametrize("name", ["config.txt", "config.notjson", "configjson"])
def test_unknown_config_extension(name: str, tmp_path: Path) -> None:
    path = tmp_path / name
    path.write_text("{}")
    with pytest.raises(ConfigurationError, match="must be JSON or YAML"):
        resolve_standalone({"config_file": path}, {})


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, False),
        (1, True),
        (0.0, False),
        (1.0, True),
        (False, False),
        (True, True),
        ("false", True),
        (None, True),
    ],
)
def test_legacy_boolean_fallback(value: object, expected: bool) -> None:
    settings = legacy_settings({"commit_changelog": value}, TerminalReporter())
    assert settings.commit_changelog is expected


def test_legacy_invalid_groups_and_values() -> None:
    settings = legacy_settings(
        {
            "header_prefix": 1,
            "changelog_filename": "a.txt",
            "version_regex": "[",
            "unknown": True,
            "group_config": [
                None,
                {"title": "Fix", "labels": ["bug"], "extra": True},
                {"title": "", "labels": []},
            ],
            "exclude_labels": ["skip", 1],
        },
        TerminalReporter(),
    )
    assert (
        settings.header_prefix == "Version:"
        and settings.changelog_filename == "CHANGELOG.md"
    )
    assert settings.group_config == (Group(title="Fix", labels=("bug",)),)
    assert settings.exclude_labels == ("skip",)


def test_environment_false_empty_lists_and_context(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"group_config": [{"title": "Fixes", "labels": ["bug"]}]}')
    settings = resolve_standalone(
        {"config_file": config},
        {
            "CHANGELOG_CI_INCLUDE_UNLABELED_CHANGES": "false",
            "CHANGELOG_CI_GROUP_CONFIG": "[]",
            "GITHUB_REPOSITORY": "o/r",
            "GITHUB_TOKEN": "secret",
        },
    )
    assert not settings.include_unlabeled_changes and settings.group_config == ()
    assert settings.repository == "o/r"
    assert settings.github_token is not None
    assert settings.github_token.get_secret_value() == "secret"
    assert "secret" not in repr(settings)
    with pytest.raises(ConfigurationError):
        resolve_standalone({}, {"CHANGELOG_CI_GROUP_CONFIG": "token-secret"})


@pytest.mark.parametrize(
    "repository", ["bad", "o/r/escape", "o/r is:issue", "../r", "o/..", "o/r?secret"]
)
def test_invalid_repository(repository: str) -> None:
    with pytest.raises(ValidationError):
        Settings(repository=repository)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com",
        "https://token@github.com",
        "https://github.com?token=secret",
        "file:///etc/passwd",
        "https://api.github.com\n",
        "https://api.github.com/\0",
    ],
)
def test_unsafe_api_url(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(api_url=url)


@pytest.mark.parametrize("field", ["header_prefix", "title"])
def test_settings_and_nested_groups_are_immutable(field: str) -> None:
    settings = Settings.model_validate(
        {
            "group_config": [{"title": "Fixes", "labels": ["bug"]}],
            "exclude_labels": ["skip"],
        }
    )
    assert settings.exclude_labels == ("skip",)
    assert settings.group_config[0].labels == ("bug",)
    target = settings if field == "header_prefix" else settings.group_config[0]
    with pytest.raises(ValidationError, match="frozen"):
        setattr(target, field, "Changed")


@pytest.mark.parametrize(
    "values",
    [
        {"header_prefix": "Release:", "release_version": "2026-10-17"},
        {
            "group_config": [{"title": "Fixes", "labels": ["bug"]}],
            "exclude_labels": ["skip"],
        },
        {"commit_changelog": False, "comment_changelog": True},
    ],
)
def test_cli_and_action_resolve_the_same_settings(
    values: dict[str, object], runner_env: dict[str, str]
) -> None:
    standalone = resolve_standalone(values, {})
    action = resolve_actions(values, runner_env, TerminalReporter())
    assert type(standalone) is Settings and type(action) is Settings
    assert standalone == action == Settings.model_validate(values)


def test_action_file_keeps_new_controls(
    tmp_path: Path, runner_env: dict[str, str]
) -> None:
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "create_pull_request": False,
                "new_branch": "notes",
                "new_pull_request_title": "Review notes",
                "commit_message": "Update notes",
                "dry_run": True,
                "diff": True,
                "quiet": True,
            }
        )
    )
    settings = resolve_actions({"config_file": config}, runner_env, TerminalReporter())
    assert settings.create_pull_request is False
    assert settings.new_branch == "notes"
    assert settings.new_pull_request_title == "Review notes"
    assert settings.commit_message == "Update notes"
    assert settings.dry_run and settings.diff and settings.quiet
    settings = resolve_actions(
        {"config_file": config},
        {**runner_env, "INPUT_DRY_RUN": "false", "INPUT_NEW_BRANCH": "other-notes"},
        TerminalReporter(),
    )
    assert not settings.dry_run
    assert settings.new_branch == "other-notes"


@pytest.mark.parametrize("field", ["dry_run", "create_pull_request"])
def test_invalid_action_file_controls_fail(
    field: str, tmp_path: Path, runner_env: dict[str, str]
) -> None:
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({field: "false"}))
    with pytest.raises(ConfigurationError, match=field):
        resolve_actions({"config_file": config}, runner_env, TerminalReporter())


def test_action_repository_settings_are_runner_owned(
    tmp_path: Path, runner_env: dict[str, str]
) -> None:
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {"repository": "wrong/repo", "api_url": "invalid", "workspace": "missing"}
        )
    )
    settings = resolve_actions(
        {
            "config_file": config,
            "repository": "another/repo",
            "workspace": "another-missing-path",
        },
        {
            **runner_env,
            "GITHUB_REPOSITORY": "o/r",
            "GITHUB_API_URL": "https://ghe.example/api/v3",
            "GITHUB_WORKSPACE": str(tmp_path),
            "INPUT_REPOSITORY": "ignored/repo",
            "INPUT_API_URL": "invalid",
            "INPUT_WORKSPACE": "missing",
        },
        TerminalReporter(),
    )
    assert settings.repository == "o/r"
    assert settings.api_url == "https://ghe.example/api/v3"
    assert settings.workspace == tmp_path


@pytest.mark.parametrize(
    "field",
    [
        "event_name",
        "event_path",
        "pull_request_title",
        "pull_request_number",
        "head_branch",
        "base_branch",
    ],
)
def test_runner_facts_are_not_configuration(field: str) -> None:
    with pytest.raises(ConfigurationError, match="Unknown configuration"):
        resolve_standalone({field: "untrusted"}, {})


@pytest.mark.parametrize(
    "extension,content",
    [
        (
            "json",
            '{"group_by":"issue_type",'
            '"group_config":[{"title":"Fixes","issue_types":["Bug"]}]}',
        ),
        (
            "yaml",
            "group_by: issue_type\ngroup_config:\n"
            "  - title: Fixes\n    issue_types: [Bug]\n",
        ),
    ],
)
def test_issue_type_configuration_and_overrides(
    extension: str, content: str, tmp_path: Path, runner_env: dict[str, str]
) -> None:
    config = tmp_path / f"settings.{extension}"
    config.write_text(content)
    explicit = {"config_file": config}
    standalone = resolve_standalone(explicit, {})
    action = resolve_actions(explicit, runner_env, TerminalReporter())
    assert standalone == action
    assert standalone.group_by == GroupBy.ISSUE_TYPE
    assert standalone.group_config == (Group(title="Fixes", issue_types=("Bug",)),)
    assert (
        resolve_standalone(explicit, {"CHANGELOG_CI_GROUP_BY": "labels"}).group_by
        == GroupBy.LABELS
    )
    assert (
        resolve_actions(
            explicit, {**runner_env, "INPUT_GROUP_BY": "labels"}, TerminalReporter()
        ).group_by
        == GroupBy.LABELS
    )
    assert (
        resolve_standalone(
            {**explicit, "group_by": "issue_type"},
            {"CHANGELOG_CI_GROUP_BY": "labels"},
        ).group_by
        == GroupBy.ISSUE_TYPE
    )


def test_issue_type_toml_configuration(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.changelog-ci]\ngroup_by = "issue_type"\n'
        '[[tool.changelog-ci.group_config]]\ntitle = "Fixes"\nissue_types = ["Bug"]\n'
    )
    settings = resolve_standalone({"workspace": tmp_path}, {})
    assert settings.group_by == GroupBy.ISSUE_TYPE
    assert settings.group_config[0].issue_types == ("Bug",)
