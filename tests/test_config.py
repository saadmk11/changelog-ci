import unittest
from unittest import mock

from scripts.config import (
    COMMIT_MESSAGE,
    Configuration,
    MARKDOWN_FILE,
    PULL_REQUEST,
)


class TestConfiguration(unittest.TestCase):

    def test_default_config(self):
        config = Configuration.create({})
        self.assertEqual(config.changelog_type, PULL_REQUEST)
        self.assertEqual(config.header_prefix, "Version:")
        self.assertEqual(config.commit_changelog, True)
        self.assertEqual(config.comment_changelog, False)
        self.assertEqual(config.pull_request_title_regex, r"^(?i:release)")

        self.assertEqual(config.version_regex, (
            r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-(("
            r"?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|["
            r"1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(["
            r"0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
        ))
        self.assertEqual(config.changelog_type, PULL_REQUEST)
        self.assertEqual(config.group_config, [])
        self.assertEqual(config.include_unlabeled_changes, True)
        self.assertEqual(config.unlabeled_group_title, "Other Changes")
        self.assertEqual(config.changelog_filename, f"CHANGELOG.{MARKDOWN_FILE}")

        self.assertEqual(config.git_committer_username, "github-actions[bot]")
        self.assertEqual(config.git_committer_email, "github-actions[bot]@users.noreply.github.com")
        self.assertEqual(
            config.git_commit_author,
            f"{config.git_committer_username} "
            f"<{config.git_committer_email}>"
        )
        self.assertEqual(config.release_version, None)
        self.assertEqual(config.github_token, None)
        self.assertEqual(config.changelog_file_type, MARKDOWN_FILE)

    @mock.patch(
        "scripts.config.Configuration.get_config_file_data",
    )
    def test_valid_changelog_type(self, get_config_file_data):
        get_config_file_data.return_value = {
            "changelog_type": "commit_message"
        }
        config = Configuration.create({'INPUT_CONFIG_FILE': 'config.json'})
        self.assertEqual(config.changelog_type, COMMIT_MESSAGE)

    @mock.patch(
        "scripts.config.Configuration.get_config_file_data",
    )
    def test_invalid_changelog_type(self, get_config_file_data):
        get_config_file_data.return_value = {
            "changelog_type": "invalid_type"
        }
        config = Configuration.create({'INPUT_CONFIG_FILE': 'config.json'})
        self.assertEqual(config.changelog_type, PULL_REQUEST)