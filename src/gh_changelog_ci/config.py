"""Load configuration files, inputs and environment variables."""

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import TypeAdapter, ValidationError

from .errors import ConfigurationError
from .models import Group, OutputMode, Settings, Source

ALIASES = {
    "git_committer_username": "committer_username",
    "git_committer_email": "committer_email",
}
LEGACY_INPUTS = frozenset(
    {
        "changelog_filename",
        "committer_username",
        "committer_email",
        "release_version",
        "github_token",
    }
)
LEGACY_FIELDS = LEGACY_INPUTS | {
    "header_prefix",
    "commit_changelog",
    "comment_changelog",
    "pull_request_title_regex",
    "version_regex",
    "changelog_type",
    "group_config",
    "exclude_labels",
    "include_unlabeled_changes",
    "unlabeled_group_title",
}
BOOL_FIELDS = frozenset(
    {
        "commit_changelog",
        "comment_changelog",
        "include_unlabeled_changes",
        "create_pull_request",
        "stdout",
        "dry_run",
        "diff",
        "verbose",
        "quiet",
        "summary",
    }
)
LIST_FIELDS = frozenset({"group_config", "exclude_labels"})
ACTION_FIELDS = LEGACY_FIELDS | {
    "create_pull_request",
    "new_branch",
    "new_pull_request_title",
    "commit_message",
    "dry_run",
    "diff",
    "verbose",
    "quiet",
    "summary",
}
GITHUB_ENV = {
    "repository": "GITHUB_REPOSITORY",
    "api_url": "GITHUB_API_URL",
    "workspace": "GITHUB_WORKSPACE",
    "github_token": "GITHUB_TOKEN",
}


class Warnings(Protocol):
    """Configuration warnings."""

    def warning(self, message: str) -> None:
        """Report a safe warning."""
        ...


def load_file(path: Path, *, toml: bool = False) -> dict[str, object]:
    """Read a JSON, YAML or TOML configuration mapping."""
    try:
        with path.open("rb") as stream:
            if toml:
                value: object = (
                    tomllib.load(stream).get("tool", {}).get("changelog-ci", {})
                )
            else:
                match path.suffix:
                    case ".yaml" | ".yml":
                        value = yaml.safe_load(stream)
                    case ".json":
                        value = json.load(stream)
                    case _:
                        raise ConfigurationError(
                            "Configuration file must be JSON or YAML."
                        )
        return TypeAdapter(dict[str, object]).validate_python(value, strict=True)
    except (OSError, ValueError, yaml.YAMLError, AttributeError) as exc:
        raise ConfigurationError(
            "Could not read configuration: "
            "missing file, invalid syntax or non-mapping data."
        ) from exc


def normalize(values: Mapping[str, object]) -> dict[str, object]:
    """Normalize aliases, enums and paths."""
    result = {ALIASES.get(key, key): value for key, value in values.items()}
    try:
        if isinstance(result.get("changelog_type"), str):
            result["changelog_type"] = Source(str(result["changelog_type"]))
        if isinstance(result.get("output_mode"), str):
            result["output_mode"] = OutputMode(str(result["output_mode"]))
        if isinstance(result.get("workspace"), str):
            result["workspace"] = Path(str(result["workspace"]))
    except ValueError as exc:
        raise ConfigurationError("Invalid changelog type or output mode.") from exc
    return result


def parse_environment(env: Mapping[str, str], prefix: str) -> dict[str, object]:
    """Parse environment values, retaining explicit false and empty arrays."""
    values: dict[str, object] = {}
    fields = (ACTION_FIELDS if prefix == "INPUT_" else Settings.model_fields.keys()) | {
        "config_file"
    }
    for key in fields:
        raw = env.get(prefix + key.upper())
        if raw is None or (prefix == "INPUT_" and raw == ""):
            continue
        if key in BOOL_FIELDS | LIST_FIELDS:
            try:
                values[key] = json.loads(raw)
            except ValueError as exc:
                raise ConfigurationError(f"Invalid JSON value for {key}.") from exc
        else:
            values[key] = raw
    return values


def validate(values: Mapping[str, object]) -> Settings:
    """Validate settings and report field names on failure."""
    values = normalize(values)
    unknown = values.keys() - Settings.model_fields.keys()
    if unknown:
        raise ConfigurationError(
            "Unknown configuration key(s). See the configuration reference."
        )
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        # Validation inputs and context can contain credentials.
        fields = ", ".join(
            sorted(
                {
                    str(e["loc"][0]) if e["loc"] else "option combination"
                    for e in exc.errors(include_input=False, include_context=False)
                }
            )
        )
        raise ConfigurationError(f"Invalid configuration: {fields}.") from exc


def resolve_standalone(
    explicit: Mapping[str, object], env: Mapping[str, str]
) -> Settings:
    """Resolve CLI > environment > selected file/workspace TOML > defaults."""
    environment: dict[str, object] = {
        key: env[name] for key, name in GITHUB_ENV.items() if env.get(name)
    }
    environment.update(parse_environment(env, "CHANGELOG_CI_"))
    selected = {**environment, **explicit}
    workspace = Path(str(selected.get("workspace", Path.cwd())))
    config_file = selected.get("config_file")
    if config_file:
        values = load_file(workspace / str(config_file))
    elif (workspace / "pyproject.toml").is_file():
        values = load_file(workspace / "pyproject.toml", toml=True)
    else:
        values = {}
    values = {**normalize(values), **environment, **explicit}
    values.pop("config_file", None)
    return validate(values)


def legacy_settings(values: Mapping[str, object], reporter: Warnings) -> Settings:
    """Normalize Action configuration values and apply fallback defaults."""
    cleaned: dict[str, object] = {}
    for raw_key, raw in values.items():
        key = ALIASES.get(raw_key, raw_key)
        if key not in LEGACY_FIELDS:
            continue
        value = raw
        if (
            key in BOOL_FIELDS
            and isinstance(value, (bool, int, float))
            and value in (0, 1)
        ):
            value = bool(value)
        elif key == "group_config" and isinstance(value, list):
            groups: list[object] = []
            for item in value:
                if isinstance(item, dict):
                    group = {k: v for k, v in item.items() if k in {"title", "labels"}}
                    try:
                        validated = Group.model_validate(group)
                    except ValidationError:
                        reporter.warning("Invalid group ignored.")
                    else:
                        groups.append(validated)
            value = groups
        elif key == "exclude_labels" and isinstance(value, list):
            # Labels from GitHub are strings.
            value = [label for label in value if isinstance(label, str)]
        if value is None or (isinstance(value, str) and not value):
            continue
        try:
            normalized = normalize({key: value})
            Settings.model_validate(normalized)
        except (ValidationError, ConfigurationError):
            reporter.warning(f"Invalid {key}; using its default.")
        else:
            cleaned.update(normalized)
    return Settings.model_validate(cleaned)


def resolve_actions(
    explicit: Mapping[str, object], env: Mapping[str, str], reporter: Warnings
) -> Settings:
    """Resolve Action configuration and runner-provided repository settings."""
    from .actions import require_github_actions

    require_github_actions(env)
    values: dict[str, object] = {
        key: env[f"INPUT_{key.upper()}"]
        for key in LEGACY_INPUTS
        if env.get(f"INPUT_{key.upper()}")
    }
    values.update(
        {key: value for key, value in explicit.items() if key in LEGACY_INPUTS}
    )
    workspace = Path(env.get("GITHUB_WORKSPACE") or Path.cwd())
    config_file = explicit.get("config_file", env.get("INPUT_CONFIG_FILE"))
    file_values: dict[str, object] = {}
    if config_file:
        try:
            file_values = load_file(workspace / str(config_file))
        except ConfigurationError:
            reporter.warning("Invalid configuration file; using input/default values.")
    settings = legacy_settings({**values, **file_values}, reporter)
    additions = {
        key: value
        for key, value in file_values.items()
        if key in ACTION_FIELDS - LEGACY_FIELDS
    }
    additions.update(
        {
            key: value
            for key, value in parse_environment(env, "INPUT_").items()
            if key in ACTION_FIELDS - LEGACY_INPUTS
        }
    )
    additions.update(
        {
            key: value
            for key, value in explicit.items()
            if key in (ACTION_FIELDS - LEGACY_INPUTS) | {"output_mode"}
        }
    )
    runtime: dict[str, object] = {
        key: env[name]
        for key, name in GITHUB_ENV.items()
        if key != "github_token" and env.get(name)
    }
    return validate({**settings.model_dump(), **additions, **runtime})
