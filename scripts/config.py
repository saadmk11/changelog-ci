import json
import re
from typing import Callable, TextIO

import yaml

from .utils import print_message


class ChangelogCIConfiguration:
    """Configuration class for Changelog CI"""

    # The regular expression used to extract semantic versioning is a
    # slightly less restrictive modification of
    # the following regular expression
    # https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
    DEFAULT_SEMVER_REGEX: str = (
        r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-(("
        r"?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|["
        r"1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(["
        r"0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    )
    DEFAULT_PULL_REQUEST_TITLE_REGEX: str = r"^(?i:release)"
    DEFAULT_VERSION_PREFIX: str = "Version:"
    DEFAULT_GROUP_CONFIG: list = []
    COMMIT_CHANGELOG: bool = True
    COMMENT_CHANGELOG: bool = False
    INCLUDE_UNLABELED_CHANGES: bool = True
    UNLABELED_GROUP_TITLE: str = "Other Changes"
    DEFAULT_COMMIT_AUTHOR: str = (
        "github-actions[bot] <github-actions[bot]@users.noreply.github.com>"
    )
    # Changelog types
    PULL_REQUEST: str = "pull_request"
    COMMIT: str = "commit_message"

    MARKDOWN_FILE: str = "md"
    RESTRUCTUREDTEXT_FILE: str = "rst"
    DEFAULT_CHANGELOG_FILENAME: str = f"CHANGELOG.{MARKDOWN_FILE}"

    def __init__(self, config_file, **other_options) -> None:
        # Initialize with default configuration
        self.header_prefix = self.DEFAULT_VERSION_PREFIX
        self.commit_changelog = self.COMMIT_CHANGELOG
        self.comment_changelog = self.COMMENT_CHANGELOG
        self.pull_request_title_regex = self.DEFAULT_PULL_REQUEST_TITLE_REGEX
        self.version_regex = self.DEFAULT_SEMVER_REGEX
        self.changelog_type = self.PULL_REQUEST
        self.group_config = self.DEFAULT_GROUP_CONFIG
        self.include_unlabeled_changes = self.INCLUDE_UNLABELED_CHANGES
        self.unlabeled_group_title = self.UNLABELED_GROUP_TITLE
        self.changelog_file_type = self.MARKDOWN_FILE
        self.changelog_filename = self.DEFAULT_CHANGELOG_FILENAME
        self.git_commit_author = self.DEFAULT_COMMIT_AUTHOR

        self.user_raw_config = self.get_user_config(config_file, other_options)

        self.validate_configuration()

    @staticmethod
    def get_user_config(config_file: str | None, other_options: dict) -> dict:
        """
        Read user provided configuration file and
        return user configuration
        """
        user_config = other_options

        if not config_file:
            print_message(
                "No Configuration file found, "
                "falling back to default configuration to parse changelog",
                message_type="warning"
            )
            return user_config

        loader: Callable[[TextIO], dict]

        try:
            # parse config files with the extension .yml and .yaml
            # using YAML syntax
            if config_file.endswith("yml") or config_file.endswith("yaml"):
                loader = yaml.safe_load
            # parse config files with the extension .json
            # using JSON syntax
            elif config_file.endswith("json"):
                loader = json.load
            else:
                print_message(
                    "We only support `JSON` or `YAML` file for configuration "
                    "falling back to default configuration to parse changelog",
                    message_type="error"
                )
                return user_config

            with open(config_file, "r") as file:
                user_config.update(loader(file))

            return user_config

        except Exception as e:
            msg = (
                f"Invalid Configuration file, error: {e}, "
                "falling back to default configuration to parse changelog"
            )
            print_message(msg, message_type="error")
            return user_config

    def validate_configuration(self) -> None:
        """
        Validate all the configuration options and
        update configuration attributes
        """
        if not self.user_raw_config:
            return

        if not isinstance(self.user_raw_config, dict):
            print_message(
                "Configuration does not contain required mapping "
                "falling back to default configuration to parse changelog",
                message_type="error"
            )
            return

        self.validate_header_prefix()
        self.validate_commit_changelog()
        self.validate_comment_changelog()
        self.validate_pull_request_title_regex()
        self.validate_version_regex()
        self.validate_changelog_type()
        self.validate_group_config()
        self.validate_include_unlabeled_changes()
        self.validate_unlabeled_group_title()
        self.validate_changelog_filename()
        self.validate_changelog_file_type()
        self.validate_git_commit_author()

    def validate_header_prefix(self) -> None:
        """Validate and set header_prefix configuration option"""
        header_prefix = self.user_raw_config.get("header_prefix")

        if not header_prefix or not isinstance(header_prefix, str):
            msg = (
                "`header_prefix` was not provided or not valid, "
                f"falling back to `{self.header_prefix}`."
            )
            print_message(msg, message_type="warning")
        else:
            self.header_prefix = header_prefix

    def validate_unlabeled_group_title(self) -> None:
        """Validate and set unlabeled_group_title configuration option"""
        unlabeled_group_title = self.user_raw_config.get("unlabeled_group_title")

        if not unlabeled_group_title or not isinstance(unlabeled_group_title, str):
            msg = (
                "`unlabeled_group_title` was not provided or not valid, "
                f"falling back to `{self.unlabeled_group_title}`."
            )
            print_message(msg, message_type="warning")
        else:
            self.unlabeled_group_title = unlabeled_group_title

    def validate_include_unlabeled_changes(self) -> None:
        """Validate and set include_unlabeled_changes configuration option"""
        include_unlabeled_changes = self.user_raw_config.get(
            "include_unlabeled_changes"
        )

        if include_unlabeled_changes not in [0, 1, False, True]:
            msg = (
                "`include_unlabeled_changes` was not provided or not valid, "
                f"falling back to `{self.include_unlabeled_changes}`."
            )
            print_message(msg, message_type="warning")
        else:
            self.include_unlabeled_changes = bool(include_unlabeled_changes)

    def validate_commit_changelog(self) -> None:
        """Validate and set commit_changelog configuration option"""
        commit_changelog = self.user_raw_config.get("commit_changelog")

        if commit_changelog not in [0, 1, False, True]:
            msg = (
                "`commit_changelog` was not provided or not valid, "
                f"falling back to `{self.commit_changelog}`."
            )
            print_message(msg, message_type="warning")
        else:
            self.commit_changelog = bool(commit_changelog)

    def validate_comment_changelog(self) -> None:
        """Validate and set comment_changelog configuration option"""
        comment_changelog = self.user_raw_config.get("comment_changelog")

        if comment_changelog not in [0, 1, False, True]:
            msg = (
                "`comment_changelog` was not provided or not valid, "
                f"falling back to `{self.comment_changelog}`."
            )
            print_message(msg, message_type="warning")
        else:
            self.comment_changelog = bool(comment_changelog)

    def validate_pull_request_title_regex(self) -> None:
        """Validate and set pull_request_title_regex configuration option"""
        pull_request_title_regex = self.user_raw_config.get(
            "pull_request_title_regex"
        )

        if not pull_request_title_regex:
            msg = (
                "`pull_request_title_regex` was not provided, "
                f"Falling back to {self.pull_request_title_regex}."
            )
            print_message(msg, message_type="warning")
            return

        try:
            # This will raise an error if the provided regex is not valid
            re.compile(pull_request_title_regex)
            self.pull_request_title_regex = pull_request_title_regex
        except Exception:
            msg = (
                "`pull_request_title_regex` is not valid, "
                f"Falling back to {self.pull_request_title_regex}."
            )
            print_message(msg, message_type="error")

    def validate_version_regex(self) -> None:
        """Validate and set validate_version_regex configuration option"""
        version_regex = self.user_raw_config.get("version_regex")

        if not version_regex:
            msg = (
                "`version_regex` was not provided, "
                f"Falling back to {self.version_regex}."
            )
            print_message(msg, message_type="warning")
            return

        try:
            # This will raise an error if the provided regex is not valid
            re.compile(version_regex)
            self.version_regex = version_regex
        except Exception:
            msg = (
                "`version_regex` is not valid, "
                f"Falling back to {self.version_regex}."
            )
            print_message(msg, message_type="warning")

    def validate_changelog_type(self) -> None:
        """Validate and set changelog_type configuration option"""
        changelog_type = self.user_raw_config.get("changelog_type")

        if not (
            changelog_type and
            isinstance(changelog_type, str) and
            changelog_type in [self.PULL_REQUEST, self.COMMIT]
        ):
            msg = (
                "`changelog_type` was not provided or not valid, "
                f"the options are '{self.PULL_REQUEST}' or '{self.COMMIT}', "
                f"falling back to default value of '{self.changelog_type}'."
            )
            print_message(msg, message_type="warning")
        else:
            self.changelog_type = changelog_type

    def validate_group_config(self) -> None:
        """Validate and set group_config configuration option"""
        group_config = self.user_raw_config.get("group_config")

        if not group_config:
            msg = "`group_config` was not provided"
            print_message(msg, message_type="warning")
            return

        if not isinstance(group_config, list):
            msg = "`group_config` is not valid, It must be an Array/List."
            print_message(msg, message_type="error")
            return

        for item in group_config:
            self.validate_group_config_item(item)

    def validate_group_config_item(self, item: dict) -> None:
        """Validate and set group_config item configuration option"""
        if not isinstance(item, dict):
            msg = (
                "`group_config` items must have key, "
                'value pairs of `title` and `labels`'
            )
            print_message(msg, message_type='error')
            return

        title = item.get('title')
        labels = item.get('labels')

        if not title or not isinstance(title, str):
            msg = (
                '`group_config` item must contain string title, '
                f'but got `{title}`'
            )
            print_message(msg, message_type='error')
            return

        if not labels or not isinstance(labels, list):
            msg = (
                '`group_config` item must contain array of labels, '
                f'but got `{labels}`'
            )
            print_message(msg, message_type='error')
            return

        if not all(isinstance(label, str) for label in labels):
            msg = (
                '`group_config` labels array must be string type, '
                f'but got `{labels}`'
            )
            print_message(msg, message_type='error')
            return

        self.group_config.append(item)

    def validate_changelog_file_type(self) -> None:
        """Validate and set changelog_file_type item configuration option"""
        if self.changelog_filename.endswith('.md'):
            self.changelog_file_type = self.MARKDOWN_FILE
        elif self.changelog_filename.endswith('.rst'):
            self.changelog_file_type = self.RESTRUCTUREDTEXT_FILE

    def validate_changelog_filename(self) -> None:
        """Validate and set changelog_filename item configuration option"""
        changelog_filename = self.user_raw_config.get('changelog_filename', '')

        if (
            changelog_filename.endswith('.md') or
            changelog_filename.endswith('.rst')
        ):
            self.changelog_filename = changelog_filename
        else:
            msg = (
                'Changelog filename was not provided or not valid, '
                f'Changelog filename must end with '
                f'"{self.MARKDOWN_FILE}" or "{self.RESTRUCTUREDTEXT_FILE}" extensions. '
                f'Falling back to `{self.changelog_filename}`.'
            )
            print_message(msg, message_type='warning')

    def validate_git_commit_author(self) -> None:
        """Validate and set changelog_filename item configuration option"""
        git_commit_author = self.user_raw_config.get('git_commit_author', '')

        if git_commit_author:
            self.git_commit_author = git_commit_author
        else:
            msg = (
                'Git Commit Author not found, '
                f'Falling back to `{self.git_commit_author}`.'
            )
            print_message(msg, message_type='warning')
