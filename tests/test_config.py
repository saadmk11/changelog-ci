import unittest
from unittest import mock

from scripts.config import (
    COMMIT_MESSAGE,
    Configuration,
    MARKDOWN_FILE,
    PULL_REQUEST,
    RESTRUCTUREDTEXT_FILE,
)


default_env_dict = {
    "INPUT_CHANGELOG_FILENAME": "MY_CHANGELOG.rst",
    "INPUT_COMMITTER_USERNAME": "changelog-ci",
    "INPUT_COMMITTER_EMAIL": "test@email.com",
    "INPUT_RELEASE_VERSION": "1.0.0",
    "INPUT_GITHUB_TOKEN": "12345",
    "INPUT_CONFIG_FILE": "config.json",
}


class TestConfiguration(unittest.TestCase):
    """Test the Configuration class"""

    def test_create_with_no_data(self):
        config = Configuration.create({})
        self.assertEqual(config.changelog_type, PULL_REQUEST)
        self.assertEqual(config.header_prefix, "Version:")
        self.assertTrue(config.commit_changelog)
        self.assertFalse(config.comment_changelog)
        self.assertEqual(config.pull_request_title_regex, "^(?i:release)")

        self.assertEqual(
            config.version_regex,
            (
                r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-(("
                r"?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|["
                r"1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(["
                r"0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
            ),
        )
        self.assertEqual(config.group_config, [])
        self.assertTrue(config.include_unlabeled_changes)
        self.assertEqual(config.unlabeled_group_title, "Other Changes")
        self.assertEqual(config.changelog_filename, f"CHANGELOG.{MARKDOWN_FILE}")

        self.assertEqual(config.git_committer_username, "github-actions[bot]")
        self.assertEqual(
            config.git_committer_email, "github-actions[bot]@users.noreply.github.com"
        )
        self.assertEqual(
            config.git_commit_author,
            f"{config.git_committer_username} <{config.git_committer_email}>",
        )
        self.assertIsNone(config.release_version)
        self.assertIsNone(config.github_token)
        self.assertEqual(config.changelog_file_type, MARKDOWN_FILE)

    @mock.patch(
        "scripts.config.Configuration.get_config_file_data",
    )
    def test_create_with_valid_data(self, get_config_file_data):
        group_config = [
            {"title": "Bug Fixes", "labels": ["bug", "bugfix"]},
            {
                "title": "Documentation Updates",
                "labels": ["docs", "documentation", "doc"],
            },
        ]
        get_config_file_data.return_value = {
            "changelog_type": "commit_message",
            "header_prefix": "Release:",
            "commit_changelog": True,
            "comment_changelog": True,
            "include_unlabeled_changes": False,
            "unlabeled_group_title": "Unlabeled Changes",
            "pull_request_title_regex": "^Release",
            "version_regex": (
                "v?([0-9]{1,2})+[.]+([0-9]{1,2})+[.]+([0-9]{"
                "1,2})\\s\\(\\d{1,2}-\\d{1,2}-\\d{4}\\)"
            ),
            "group_config": group_config,
        }
        config = Configuration.create(default_env_dict)

        self.assertEqual(config.changelog_type, COMMIT_MESSAGE)
        self.assertEqual(config.header_prefix, "Release:")
        self.assertTrue(config.commit_changelog)
        self.assertTrue(config.comment_changelog)
        self.assertEqual(config.pull_request_title_regex, "^Release")

        self.assertEqual(
            config.version_regex,
            (
                "v?([0-9]{1,2})+[.]+([0-9]{1,2})+[.]+([0-9]{"
                "1,2})\\s\\(\\d{1,2}-\\d{1,2}-\\d{4}\\)"
            ),
        )
        self.assertEqual(config.group_config, group_config)
        self.assertFalse(config.include_unlabeled_changes)
        self.assertEqual(config.unlabeled_group_title, "Unlabeled Changes")
        self.assertEqual(config.changelog_filename, "MY_CHANGELOG.rst")

        self.assertEqual(config.git_committer_username, "changelog-ci")
        self.assertEqual(config.git_committer_email, "test@email.com")
        self.assertEqual(
            config.git_commit_author,
            f"{config.git_committer_username} <{config.git_committer_email}>",
        )
        self.assertEqual(config.release_version, "1.0.0")
        self.assertEqual(config.github_token, "12345")
        self.assertEqual(config.changelog_file_type, RESTRUCTUREDTEXT_FILE)

    @mock.patch(
        "scripts.config.Configuration.get_config_file_data",
    )
    def test_create_with_invalid_data(self, get_config_file_data):
        get_config_file_data.return_value = {
            "changelog_type": "invalid_changelog_type",
            "header_prefix": 1,
            "commit_changelog": "test",
            "comment_changelog": "test",
            "include_unlabeled_changes": "test",
            "unlabeled_group_title": None,
            "pull_request_title_regex": None,
            "version_regex": 123,
            "group_config": "text",
        }
        config = Configuration.create(
            {
                "INPUT_CHANGELOG_FILENAME": "MY_CHANGELOG.xyz",
                "INPUT_COMMITTER_USERNAME": None,
                "INPUT_COMMITTER_EMAIL": None,
                "INPUT_RELEASE_VERSION": None,
                "INPUT_GITHUB_TOKEN": "",
                "INPUT_CONFIG_FILE": "config.json",
            }
        )

        self.assertEqual(config.changelog_type, PULL_REQUEST)
        self.assertEqual(config.header_prefix, "Version:")
        self.assertTrue(config.commit_changelog)
        self.assertFalse(config.comment_changelog)
        self.assertEqual(config.pull_request_title_regex, "^(?i:release)")

        self.assertEqual(
            config.version_regex,
            (
                r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-(("
                r"?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|["
                r"1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(["
                r"0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
            ),
        )
        self.assertEqual(config.group_config, [])
        self.assertTrue(config.include_unlabeled_changes)
        self.assertEqual(config.unlabeled_group_title, "Other Changes")
        self.assertEqual(config.changelog_filename, f"CHANGELOG.{MARKDOWN_FILE}")

        self.assertEqual(config.git_committer_username, "github-actions[bot]")
        self.assertEqual(
            config.git_committer_email, "github-actions[bot]@users.noreply.github.com"
        )
        self.assertEqual(
            config.git_commit_author,
            f"{config.git_committer_username} <{config.git_committer_email}>",
        )
        self.assertIsNone(config.release_version)
        self.assertIsNone(config.github_token)
        self.assertEqual(config.changelog_file_type, MARKDOWN_FILE)

    @mock.patch(
        "scripts.config.Configuration.get_config_file_data",
    )
    def test_changelog_file_type(self, get_config_file_data):
        get_config_file_data.return_value = {"changelog_filename": "CHANGELOG.rst"}
        config = Configuration.create(default_env_dict)
        self.assertEqual(config.changelog_file_type, RESTRUCTUREDTEXT_FILE)

    @mock.patch(
        "scripts.config.Configuration.get_config_file_data",
    )
    def test_invalid_changelog_file_type(self, get_config_file_data):
        get_config_file_data.return_value = {"changelog_filename": "CHANGELOG.xyz"}
        config = Configuration.create(default_env_dict)
        self.assertEqual(config.changelog_file_type, MARKDOWN_FILE)

    def test_git_commit_author(self):
        default_env_dict = {
            "INPUT_COMMITTER_USERNAME": "changelog-ci",
            "INPUT_COMMITTER_EMAIL": "test@email.com",
        }
        config = Configuration.create(default_env_dict)
        self.assertEqual(config.git_commit_author, "changelog-ci <test@email.com>")

    def test_get_user_config_without_file(self):
        self.assertEqual(
            Configuration.get_user_config(default_env_dict),
            {
                "changelog_filename": "MY_CHANGELOG.rst",
                "git_committer_email": "test@email.com",
                "git_committer_username": "changelog-ci",
                "github_token": "12345",
                "release_version": "1.0.0",
            },
        )

    @mock.patch(
        "scripts.config.Configuration.get_config_file_data",
    )
    def test_get_user_config_with_file(self, get_config_file_data):
        get_config_file_data.return_value = {
            "changelog_filename": "CHANGELOG.md",
            "changelog_type": "commit_message",
            "header_prefix": "Release:",
        }
        self.assertEqual(
            Configuration.get_user_config(default_env_dict),
            {
                "changelog_filename": "CHANGELOG.md",
                "git_committer_email": "test@email.com",
                "git_committer_username": "changelog-ci",
                "github_token": "12345",
                "release_version": "1.0.0",
                "changelog_type": "commit_message",
                "header_prefix": "Release:",
            },
        )

    def test_clean_header_prefix(self):
        self.assertEqual(Configuration.clean_header_prefix("Release:"), "Release:")
        self.assertIsNone(Configuration.clean_header_prefix(1))

    def test_clean_commit_changelog(self):
        self.assertFalse(Configuration.clean_commit_changelog(False))
        self.assertTrue(Configuration.clean_commit_changelog(1))
        self.assertIsNone(Configuration.clean_commit_changelog("test"))

    def test_clean_comment_changelog(self):
        self.assertFalse(Configuration.clean_comment_changelog(False))
        self.assertTrue(Configuration.clean_comment_changelog(1))
        self.assertIsNone(Configuration.clean_comment_changelog("test"))

    def test_clean_pull_request_title_regex(self):
        self.assertIsNone(Configuration.clean_pull_request_title_regex(1))
        self.assertEqual(
            Configuration.clean_pull_request_title_regex("^Release"), "^Release"
        )
        self.assertIsNone(Configuration.clean_pull_request_title_regex("^["))

    def test_clean_version_regex(self):
        self.assertIsNone(Configuration.clean_version_regex(1))
        self.assertEqual(
            Configuration.clean_version_regex(
                "v?([0-9]{1,2})+[.]+([0-9]{1,2})+[.]+"
                "([0-9]{1,2})\\s\\(\\d{1,2}-\\d{1,2}-\\d{4}\\)"
            ),
            (
                "v?([0-9]{1,2})+[.]+([0-9]{1,2})+[.]+"
                "([0-9]{1,2})\\s\\(\\d{1,2}-\\d{1,2}-\\d{4}\\)"
            ),
        )
        self.assertIsNone(Configuration.clean_version_regex("^["))

    def test_clean_changelog_type(self):
        self.assertEqual(Configuration.clean_changelog_type(PULL_REQUEST), PULL_REQUEST)
        self.assertIsNone(Configuration.clean_changelog_type(1))
        self.assertIsNone(Configuration.clean_changelog_type("test"))

    def test_clean_include_unlabeled_changes(self):
        self.assertFalse(Configuration.clean_include_unlabeled_changes(False))
        self.assertTrue(Configuration.clean_include_unlabeled_changes(1))
        self.assertIsNone(Configuration.clean_include_unlabeled_changes("test"))

    def test_clean_unlabeled_group_title(self):
        self.assertEqual(Configuration.clean_unlabeled_group_title("test"), "test")
        self.assertIsNone(Configuration.clean_unlabeled_group_title(1))

    def test_clean_changelog_filename(self):
        self.assertEqual(Configuration.clean_changelog_filename("test.md"), "test.md")
        self.assertEqual(Configuration.clean_changelog_filename("test.rst"), "test.rst")
        self.assertIsNone(Configuration.clean_changelog_filename(1))
        self.assertIsNone(Configuration.clean_changelog_filename("test.xyz"))

    def test_clean_git_committer_username(self):
        self.assertEqual(Configuration.clean_git_committer_username("test"), "test")

        self.assertIsNone(Configuration.clean_git_committer_username(1))
        self.assertIsNone(Configuration.clean_git_committer_username(True))

    def test_clean_git_committer_email(self):
        self.assertEqual(
            Configuration.clean_git_committer_email("test@email.com"), "test@email.com"
        )

        self.assertIsNone(Configuration.clean_git_committer_email(1))
        self.assertIsNone(Configuration.clean_git_committer_email(True))

    def test_clean_release_version(self):
        self.assertEqual(Configuration.clean_release_version("1.2.3"), "1.2.3")

        self.assertIsNone(Configuration.clean_release_version(1.1))
        self.assertIsNone(Configuration.clean_release_version(True))

    def test_clean_group_config(self):
        group_config = [
            {"title": "Bug Fixes", "labels": ["bug", "bugfix"]},
            {
                "title": "Documentation Updates",
                "labels": ["docs", "documentation", "doc"],
            },
        ]
        self.assertEqual(Configuration.clean_group_config(group_config), group_config)

        self.assertIsNone(Configuration.clean_group_config("test"))
        self.assertIsNone(Configuration.clean_group_config([]))

    def test_clean_group_config_item(self):
        group_config_item = {"title": "Bug Fixes", "labels": ["bug", "bugfix"]}

        self.assertEqual(
            Configuration._clean_group_config_item(group_config_item), group_config_item
        )

        self.assertIsNone(
            Configuration._clean_group_config_item({"title": "test", "labels": None})
        )
        self.assertIsNone(Configuration._clean_group_config_item({"title": "test"}))
