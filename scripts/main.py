import abc
import os
import re
import time
from typing import Any

import github_action_utils as gha_utils  # type: ignore
import requests

from .builders import (
    ChangelogBuilderBase,
    CommitMessageChangelogBuilder,
    PullRequestChangelogBuilder,
)
from .config import (
    COMMIT_MESSAGE,
    MARKDOWN_FILE,
    PULL_REQUEST,
    RESTRUCTUREDTEXT_FILE,
    ActionEnvironment,
    Configuration,
)
from .run_git import (
    checkout_pull_request_branch,
    configure_git_author,
    create_new_git_branch,
    git_commit_changelog,
)
from .utils import display_whats_new, get_request_headers


class ChangelogCIBase(abc.ABC):
    """Base Class for Changelog CI"""

    GITHUB_API_URL: str = "https://api.github.com"

    def __init__(self, config: Configuration, action_env: ActionEnvironment) -> None:
        self.config = config
        self.action_env = action_env
        self.event_payload = self.action_env.event_payload

        self.release_version = self._get_release_version()
        self.builder: ChangelogBuilderBase = self._get_changelog_builder(
            config, action_env, self.release_version
        )

    @property
    def _open_file_mode(self) -> str:
        """Gets the mode that the changelog file should be opened in"""
        if os.path.exists(self.config.changelog_filename):
            # if the changelog file exists
            # opens it in read-write mode
            file_mode = "r+"
        else:
            # if the changelog file does not exist
            # opens it in read-write mode
            # but creates the file first also
            file_mode = "w+"

        return file_mode

    @property
    def _comment_issue_number(self) -> Any:
        """Issue number to comment on"""
        return None

    @property
    @abc.abstractmethod
    def _commit_branch_name(self) -> str:
        """Get the name of the branch to commit the changelog to"""
        pass

    @abc.abstractmethod
    def _get_release_version(self) -> str:
        """Get the release version"""
        pass

    @staticmethod
    def _get_changelog_builder(
        config: Configuration, action_env: ActionEnvironment, release_version: str
    ) -> ChangelogBuilderBase:
        """Get changelog Builder"""
        if config.changelog_type == PULL_REQUEST:
            return PullRequestChangelogBuilder(config, action_env, release_version)
        elif config.changelog_type == COMMIT_MESSAGE:
            return CommitMessageChangelogBuilder(config, action_env, release_version)
        else:
            raise ValueError(f"Unknown changelog type: {config.changelog_type}")

    def _update_changelog_file(self, string_data: str) -> None:
        """Write changelog to the changelog file"""
        with open(self.config.changelog_filename, self._open_file_mode) as f:
            # read the existing data and store it in a variable
            body = f.read()
            # write at the top of the file
            f.seek(0, 0)
            f.write(string_data)

            if body:
                # re-write the existing data
                f.write("\n\n")
                f.write(body)

    def _commit_changelog(self, commit_branch_name: str) -> None:
        """Commit Changelog"""
        commit_message = (
            f"[Changelog CI] Add Changelog for Version {self.release_version}"
        )
        git_commit_changelog(
            commit_message,
            self.config.changelog_filename,
            self.config.git_commit_author,
            commit_branch_name,
        )

    def _create_pull_request(self, branch_name: str, body: str) -> None:
        """Create pull request on GitHub"""
        url = f"{self.GITHUB_API_URL}/repos/{self.action_env.repository}/pulls"
        payload = {
            "title": f"[Changelog CI] Add Changelog for Version {self.release_version}",
            "head": branch_name,
            "base": self.action_env.base_branch,
            "body": body,
        }

        response = requests.post(
            url, json=payload, headers=get_request_headers(self.config.github_token)
        )

        if response.status_code == 201:
            html_url = response.json()["html_url"]
            gha_utils.notice(f"Pull request opened at {html_url} \U0001F389")
        else:
            gha_utils.error(
                f"Could not create a pull request on "
                f"{self.action_env.repository}, status code: {response.status_code}"
            )

    def _comment_changelog(self, changelog_string: str) -> None:
        """Comments Changelog to an issue"""
        if not self.config.github_token:
            # Token is required by the GitHub API to create a Comment
            # if not provided exit with error message
            gha_utils.error(
                "Could not add a comment. "
                "`github_token` input is required for this operation. "
                "If you want to enable Changelog comment, please add "
                "`github_token` to your workflow yaml file. "
                "Look at Changelog CI's documentation for more information."
            )
            return

        issue_number = self._comment_issue_number

        if not issue_number:
            return

        owner, repo = self.action_env.repository.split("/")

        payload = {
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
            "body": changelog_string,
        }

        url = (
            f"{self.GITHUB_API_URL}/repos/{self.action_env.repository}/"
            f"issues/{issue_number}/comments"
        )

        response = requests.post(
            url, headers=get_request_headers(self.config.github_token), json=payload
        )

        if response.status_code != 201:
            # API should return 201, otherwise show error message
            gha_utils.warning(
                f"Error while trying to create a comment. "
                f"GitHub API returned error response for "
                f"{self.action_env.repository}, status code: {response.status_code}"
            )
        else:
            gha_utils.notice(
                f"Comment added at {response.json()['html_url']} \U0001F389"
            )

    def run(self) -> None:
        """Entrypoint to the Changelog CI"""
        if not self.config.commit_changelog and not self.config.comment_changelog:
            # if both commit_changelog and comment_changelog is set to false
            # then exit with warning and don't generate Changelog
            gha_utils.error(
                "Skipping Changelog generation as both `commit_changelog` "
                "and `comment_changelog` is set to False. "
                "If you did not intend to do this please set "
                "one or both of them to True."
            )
            raise SystemExit(1)

        changelog_string = self.builder.build()

        if self.config.commit_changelog:
            self._update_changelog_file(changelog_string)
            self._commit_changelog(self._commit_branch_name)

        if self.config.comment_changelog:
            with gha_utils.group("Comment Changelog"):
                if self.config.changelog_file_type == RESTRUCTUREDTEXT_FILE:
                    markdown_changelog_string = self.builder.parse_changelog(
                        MARKDOWN_FILE
                    )
                else:
                    markdown_changelog_string = changelog_string

                self._comment_changelog(markdown_changelog_string)

        gha_utils.set_output("changelog", changelog_string)


class ChangelogCIPullRequestEvent(ChangelogCIBase):
    """Generates, commits and/or comments changelog using pull requests"""

    def __init__(self, config: Configuration, action_env: ActionEnvironment) -> None:
        super().__init__(config, action_env)
        self._check_pull_request_title()

    @property
    def _commit_branch_name(self) -> str:
        """Get the name of the branch to commit the changelog to"""
        return self.action_env.pull_request_branch

    def _get_release_version(self) -> str:
        """Get release version number from the pull request title or user Input"""
        pull_request_title = self.event_payload["pull_request"]["title"]
        pattern = re.compile(self.config.version_regex)
        match = pattern.search(pull_request_title)

        if match:
            return match.group()

        release_version = self.config.release_version

        if release_version:
            return release_version

        # if the pull request title is not valid,
        # and `release_version` input not provided then exit
        # It might happen if the pull request is not meant to be release
        # or the title was not accurate.
        gha_utils.error(
            "Could not find matching version number from pull request title. "
            f"Regex tried: {self.config.version_regex} "
            "and `release_version` input was also not provided."
            "Aborting Changelog Generation"
        )
        raise SystemExit(0)

    @property
    def _comment_issue_number(self) -> Any:
        """Get pull request number from the event payload"""
        return self.event_payload["number"]

    def _check_pull_request_title(self) -> None:
        """Check if changelog should be generated for this pull request"""
        pull_request_title = self.event_payload["pull_request"]["title"]
        pattern = re.compile(self.config.pull_request_title_regex)
        match = pattern.search(pull_request_title)

        if not match and not self.config.release_version:
            # if pull request regex doesn't match then exit
            # and don't generate changelog
            gha_utils.error(
                "The title of the pull request did not match. "
                f'Regex tried: "{self.config.pull_request_title_regex}", '
                "and `release_version` input was also not provided. "
                "Aborting Changelog Generation."
            )
            raise SystemExit(0)


class ChangelogCICustomEvent(ChangelogCIBase):
    """Generates, commits and/or comments changelog using commit messages"""

    @property
    def _commit_branch_name(self) -> str:
        """Get the name of the branch to commit the changelog to"""
        return self._create_new_branch()

    def _comment_changelog(self, changelog_string: str) -> None:
        """Comment changelog on GitHub"""
        gha_utils.error(
            "`comment_changelog` can only be used "
            "if Changelog CI is triggered on a pull request event. "
            "Please Check the Documentation for more details."
        )

    def _create_new_branch(self) -> str:
        """Creates a new branch"""
        # Use timestamp to ensure uniqueness of the new branch
        new_branch = f"changelog-ci-{self.release_version}-{int(time.time())}"
        create_new_git_branch(self.action_env.base_branch, new_branch)
        return new_branch

    def _commit_changelog(self, commit_branch_name: str) -> None:
        """Commits the changelog to the new branch and creates a pull request"""
        super()._commit_changelog(commit_branch_name)

        if self.config.changelog_file_type == RESTRUCTUREDTEXT_FILE:
            markdown_changelog_string = self.builder.parse_changelog(MARKDOWN_FILE)
        else:
            markdown_changelog_string = self.builder.changelog_string

        with gha_utils.group("Create Pull Request"):
            self._create_pull_request(commit_branch_name, markdown_changelog_string)

    def _get_release_version(self) -> str:
        """Get release version from user Input"""
        release_version = self.config.release_version

        if not release_version:
            gha_utils.error(
                "`release_version` input must be provided to generate Changelog. "
                "Please Check the Documentation for more details. "
                "Aborting Changelog Generation"
            )
            raise SystemExit(1)

        return release_version


if __name__ == "__main__":
    with gha_utils.group("Parse Configuration"):
        user_configuration = Configuration.create(os.environ)
        action_environment = ActionEnvironment.from_env(os.environ)

    if action_environment.pull_request_branch:
        # Checkout git pull request branch
        checkout_pull_request_branch(action_environment.pull_request_branch)

    # Configure Git Author
    configure_git_author(
        user_configuration.git_committer_username,
        user_configuration.git_committer_email,
    )

    # Group: Generate Changelog
    with gha_utils.group("Generate Changelog"):
        # Get CI class using configuration
        changelog_ci_class = (
            ChangelogCIPullRequestEvent
            if action_environment.event_name == PULL_REQUEST
            else ChangelogCICustomEvent
        )
        # Initialize the Changelog CI
        ci = changelog_ci_class(user_configuration, action_environment)
        # Run Changelog CI
        ci.run()

    display_whats_new()
