import json
import re
from typing import Any, Callable, Mapping, NamedTuple, TextIO

import github_action_utils as gha_utils  # type: ignore
import yaml

# Changelog Types
PULL_REQUEST: str = "pull_request"
COMMIT_MESSAGE: str = "commit_message"

# Changelog File Extensions
MARKDOWN_FILE: str = "md"
RESTRUCTUREDTEXT_FILE: str = "rst"


UserConfigType = dict[str, str | bool | list[dict[str, str | list[str]]] | None]


class ActionEnvironment(NamedTuple):
    event_path: str
    repository: str
    pull_request_branch: str
    base_branch: str
    event_name: str
    event_payload: dict[str, Any]

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ActionEnvironment":
        return cls(
            event_path=env["GITHUB_EVENT_PATH"],
            repository=env["GITHUB_REPOSITORY"],
            pull_request_branch=env["GITHUB_HEAD_REF"],
            base_branch=env["GITHUB_REF"],
            event_name=env["GITHUB_EVENT_NAME"],
            event_payload=gha_utils.event_payload(),
        )


class Configuration(NamedTuple):
    """Configuration class for Changelog CI"""

    header_prefix: str = "Version:"
    commit_changelog: bool = True
    comment_changelog: bool = False
    pull_request_title_regex: str = r"^(?i:release)"
    # The regular expression used to extract semantic versioning is a
    # slightly less restrictive modification of
    # the following regular expression
    # https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
    version_regex: str = (
        r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-(("
        r"?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|["
        r"1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(["
        r"0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    )
    changelog_type: str = PULL_REQUEST
    group_config: list[dict[str, str | list[str]]] = []
    include_unlabeled_changes: bool = True
    unlabeled_group_title: str = "Other Changes"
    changelog_filename: str = f"CHANGELOG.{MARKDOWN_FILE}"

    git_committer_username: str = "github-actions[bot]"
    git_committer_email: str = "github-actions[bot]@users.noreply.github.com"
    release_version: str | None = None
    github_token: str | None = None

    @property
    def changelog_file_type(self) -> str:
        """changelog_file_type option"""
        if self.changelog_filename.endswith(".rst"):
            return RESTRUCTUREDTEXT_FILE
        return MARKDOWN_FILE

    @property
    def git_commit_author(self) -> str:
        """git_commit_author option"""
        return f"{self.git_committer_username} <{self.git_committer_email}>"

    @classmethod
    def create(cls, env: Mapping[str, str | None]) -> "Configuration":
        """
        Create a Configuration object
        from a config file and environment variables
        """
        cleaned_user_config = cls.clean_user_config(cls.get_user_config(env))
        return cls(**cleaned_user_config)

    @classmethod
    def get_user_config(cls, env: Mapping[str, str | None]) -> UserConfigType:
        """
        Read user provided configuration file and input and
        return user configuration
        """
        user_config: UserConfigType = {
            "changelog_filename": env.get("INPUT_CHANGELOG_FILENAME"),
            "git_committer_username": env.get("INPUT_COMMITTER_USERNAME"),
            "git_committer_email": env.get("INPUT_COMMITTER_EMAIL"),
            "release_version": env.get("INPUT_RELEASE_VERSION"),
            "github_token": env.get("INPUT_GITHUB_TOKEN"),
        }
        config_file_path = env.get("INPUT_CONFIG_FILE")

        if not config_file_path:
            gha_utils.warning(
                "No Configuration file found, "
                "falling back to default configuration to parse changelog"
            )
            return user_config

        config_file_data = cls.get_config_file_data(config_file_path)
        user_config.update(config_file_data)

        return user_config

    @staticmethod
    def get_config_file_data(config_file_path: str) -> UserConfigType:
        """
        Open config file and return file data
        """
        loader: Callable[[TextIO], dict[str, Any]]
        config_file_data: dict[str, Any] = {}

        try:
            # parse config files with the extension .yml and .yaml
            # using YAML syntax
            if config_file_path.endswith("yml") or config_file_path.endswith("yaml"):
                loader = yaml.safe_load
            # parse config files with the extension .json
            # using JSON syntax
            elif config_file_path.endswith("json"):
                loader = json.load
            else:
                gha_utils.error(
                    "We only support `JSON` or `YAML` file for configuration "
                    "falling back to default configuration to parse changelog"
                )
                return config_file_data

            with open(config_file_path, "r") as file:
                config_file_data = loader(file)

        except Exception as e:
            gha_utils.error(
                f"Invalid Configuration file, error: {e}, "
                "falling back to default configuration to parse changelog"
            )
        return config_file_data

    @classmethod
    def clean_user_config(cls, user_config: dict[str, Any]) -> dict[str, Any]:
        if not user_config:
            return user_config

        cleaned_user_config: dict[str, Any] = {}

        for key, value in user_config.items():
            if key in cls._fields:
                cleand_value = getattr(cls, f"clean_{key.lower()}", lambda x: None)(
                    value
                )
                if cleand_value is not None:
                    cleaned_user_config[key] = cleand_value

        return cleaned_user_config

    @classmethod
    def clean_header_prefix(cls, value: Any) -> str | None:
        """clean header_prefix configuration option"""
        if not value or not isinstance(value, str):
            gha_utils.warning(
                "`header_prefix` was not provided or not valid, "
                "falling back to default value."
            )
            return None
        return value

    @classmethod
    def clean_commit_changelog(cls, value: Any) -> bool | None:
        """clean commit_changelog configuration option"""
        if value not in [0, 1, False, True]:
            gha_utils.warning(
                "`commit_changelog` was not provided or not valid, "
                "falling back to default value."
            )
            return None
        return bool(value)

    @classmethod
    def clean_comment_changelog(cls, value: Any) -> bool | None:
        """clean comment_changelog configuration option"""
        if value not in [0, 1, False, True]:
            gha_utils.warning(
                "`comment_changelog` was not provided or not valid, "
                "falling back to default value."
            )
            return None
        return bool(value)

    @classmethod
    def clean_pull_request_title_regex(cls, value: str) -> str | None:
        """clean pull_request_title_regex configuration option"""
        if not value:
            gha_utils.warning(
                "`pull_request_title_regex` was not provided, "
                "Falling back to default."
            )
            return None

        try:
            # This will raise an error if the provided regex is not valid
            re.compile(value)
            return value
        except Exception:
            gha_utils.error(
                "`pull_request_title_regex` is not valid, "
                "Falling back to default value."
            )
            return None

    @classmethod
    def clean_version_regex(cls, value: str) -> str | None:
        """clean validate_version_regex configuration option"""
        if not value:
            gha_utils.warning(
                "`version_regex` was not provided, Falling back to default value."
            )
            return None

        try:
            # This will raise an error if the provided regex is not valid
            re.compile(value)
            return value
        except Exception:
            gha_utils.warning(
                "`version_regex` is not valid, Falling back to default value."
            )
            return None

    @classmethod
    def clean_changelog_type(cls, value: Any) -> str | None:
        """clean changelog_type configuration option"""
        if not (
            value and isinstance(value, str) and value in [PULL_REQUEST, COMMIT_MESSAGE]
        ):
            gha_utils.warning(
                "`changelog_type` was not provided or not valid, "
                f"the options are '{PULL_REQUEST}' or '{COMMIT_MESSAGE}', "
                f"falling back to default."
            )
            return None
        return value

    @classmethod
    def clean_include_unlabeled_changes(cls, value: Any) -> bool | None:
        """clean include_unlabeled_changes configuration option"""
        if value not in [0, 1, False, True]:
            gha_utils.warning(
                "`include_unlabeled_changes` was not provided or not valid, "
                "falling back to default value."
            )
            return None

        return bool(value)

    @classmethod
    def clean_unlabeled_group_title(cls, value: Any) -> str | None:
        """clean unlabeled_group_title configuration option"""
        if not value or not isinstance(value, str):
            gha_utils.warning(
                "`unlabeled_group_title` was not provided or not valid, "
                "falling back to default value."
            )
            return None
        return value

    @classmethod
    def clean_changelog_filename(cls, value: Any) -> str | None:
        """clean changelog_filename item configuration option"""
        if (
            value
            and isinstance(value, str)
            and (value.endswith(".md") or value.endswith(".rst"))
        ):
            return value
        else:
            gha_utils.warning(
                "Changelog filename was not provided or not valid, "
                f"Changelog filename must end with "
                f'"{MARKDOWN_FILE}" or "{RESTRUCTUREDTEXT_FILE}" extensions. '
                f"Falling back to default value."
            )
            return None

    @classmethod
    def clean_git_committer_username(cls, value: Any) -> str | None:
        """clean git_committer_username item configuration option"""
        if value and isinstance(value, str):
            return value
        else:
            gha_utils.warning(
                "`git_committer_username` was not provided, "
                "Falling back to default value."
            )
            return None

    @classmethod
    def clean_git_committer_email(cls, value: Any) -> str | None:
        """clean git_committer_email item configuration option"""
        if value and isinstance(value, str):
            return value
        else:
            gha_utils.warning(
                "`git_committer_email` was not provided, "
                "Falling back to default value."
            )
            return None

    @classmethod
    def clean_release_version(cls, value: Any) -> str | None:
        """clean release_version item configuration option"""
        if value and isinstance(value, str):
            return value
        else:
            gha_utils.notice("`release_version` was not provided as an input.")
            return None

    @classmethod
    def clean_github_token(cls, value: Any) -> str | None:
        """clean release_version item configuration option"""
        if value and isinstance(value, str):
            return value
        else:
            gha_utils.notice("`github_token` was not provided as an input.")
            return None

    @classmethod
    def clean_group_config(cls, value: Any) -> list[dict[str, Any]] | None:
        """clean group_config configuration option"""
        group_config = []

        if not value:
            gha_utils.warning("`group_config` was not provided")
            return None

        if not isinstance(value, list):
            gha_utils.error("`group_config` is not valid, It must be an Array/List.")
            return None

        for item in value:
            cleaned_group_config_item = cls._clean_group_config_item(item)
            if cleaned_group_config_item:
                group_config.append(cleaned_group_config_item)

        return group_config

    @classmethod
    def _clean_group_config_item(
        cls, value: dict[str, str | list[str]]
    ) -> dict[str, str | list[str]] | None:
        """clean group_config item configuration option"""
        if not isinstance(value, dict):
            gha_utils.error(
                "`group_config` items must have key, "
                "value pairs of `title` and `labels`"
            )
            return None

        title = value.get("title")
        labels = value.get("labels")

        if not title or not isinstance(title, str):
            gha_utils.error(
                "`group_config` item must contain string title, " f"but got `{title}`"
            )
            return None

        if not labels or not isinstance(labels, list):
            gha_utils.error(
                "`group_config` item must contain array of labels, "
                f"but got `{labels}`"
            )
            return None

        if not all(isinstance(label, str) for label in labels):
            gha_utils.error(
                "`group_config` labels array must be string type, "
                f"but got `{labels}`"
            )
            return None

        return value
