import abc
import copy
import os
import re
import time
from functools import lru_cache
from typing import Any

import github_action_utils as gha_utils  # type: ignore
import requests

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
from .utils import display_whats_new


class ChangelogCIBase(abc.ABC):
    """Base Class for Changelog CI"""

    GITHUB_API_URL: str = "https://api.github.com"

    WORKFLOW_DISPATCH_EVENT: str = "workflow_dispatch"
    PULL_REQUEST_EVENT: str = "pull_request"

    def __init__(self, config: Configuration, action_env: ActionEnvironment) -> None:
        self.config = config
        self.action_env = action_env
        self.event_payload = self.action_env.event_payload
        self.release_version = self._get_release_version()

        self.changelog_string = ""
        self.change_list: list[dict[str, Any]] = []

    @property
    def _get_request_headers(self) -> dict[str, str]:
        """Get headers for GitHub API request"""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.config.github_token:
            headers.update({"authorization": f"Bearer {self.config.github_token}"})

        return headers

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

    @abc.abstractmethod
    def _get_changes_after_last_release(self) -> list[dict[str, Any]]:
        """Get changes list after last release"""
        pass

    @lru_cache
    @abc.abstractmethod
    def _parse_changelog(self, file_type: str) -> str:
        """Parse changelog, and build the changelog string (Markdown or ReStructuredText)"""
        pass

    @abc.abstractmethod
    def _comment_changelog(self, changelog_string: str) -> None:
        """Comment changelog on GitHub"""
        pass

    @property
    @abc.abstractmethod
    def _commit_branch_name(self) -> str:
        """Get the name of the branch to commit the changelog to"""
        pass

    @abc.abstractmethod
    def _get_release_version(self) -> str:
        """Returns the release version"""
        pass

    def _get_latest_release_date(self) -> str:
        """Using GitHub API gets the latest release date"""
        url = (
            f"{self.GITHUB_API_URL}/repos/"
            f"{self.action_env.repository}/releases/latest"
        )

        response = requests.get(url, headers=self._get_request_headers)

        published_date = ""

        if response.status_code == 200:
            response_data = response.json()
            # get the published date of the latest release
            published_date = response_data["published_at"]
        else:
            # if there is no previous release API will return 404 Not Found
            gha_utils.warning(
                f"Could not find any previous release for "
                f"{self.action_env.repository}, status code: {response.status_code}"
            )
        return published_date

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

        response = requests.post(url, json=payload, headers=self._get_request_headers)

        if response.status_code == 201:
            html_url = response.json()["html_url"]
            gha_utils.notice(f"Pull request opened at {html_url} \U0001F389")
        else:
            gha_utils.error(
                f"Could not create a pull request on "
                f"{self.action_env.repository}, status code: {response.status_code}"
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

        self.change_list = self._get_changes_after_last_release()

        # exit the method if there is no changes found
        if not self.change_list:
            raise SystemExit(0)

        self.changelog_string = self._parse_changelog(self.config.changelog_file_type)

        if self.config.commit_changelog:
            self._update_changelog_file(self.changelog_string)
            self._commit_changelog(self._commit_branch_name)

        if self.config.comment_changelog:
            with gha_utils.group("Comment Changelog"):
                if self.config.changelog_file_type == RESTRUCTUREDTEXT_FILE:
                    markdown_changelog_string = self._parse_changelog(MARKDOWN_FILE)
                else:
                    markdown_changelog_string = self.changelog_string

                self._comment_changelog(markdown_changelog_string)

        gha_utils.set_output("changelog", self.changelog_string)


class ChangelogCIPullRequest(ChangelogCIBase):
    """Generates, commits and/or comments changelog using pull requests"""

    @staticmethod
    def _get_changelog_line(file_type: str, item: dict[str, Any]) -> str:
        """Generate each line of changelog"""
        if file_type == MARKDOWN_FILE:
            changelog_line_template = "* [#{number}]({url}): {title}\n"
        else:
            changelog_line_template = "* `#{number} <{url}>`__: {title}\n"

        return changelog_line_template.format(
            number=item["number"], url=item["url"], title=item["title"]
        )

    def _comment_changelog(self, changelog_string: str) -> None:
        """Comments Changelog to the pull request"""
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
            return None

        pull_request_number = self.event_payload["number"]

        owner, repo = self.action_env.repository.split("/")

        payload = {
            "owner": owner,
            "repo": repo,
            "issue_number": pull_request_number,
            "body": changelog_string,
        }

        url = (
            f"{self.GITHUB_API_URL}/repos/{self.action_env.repository}/"
            f"issues/{pull_request_number}/comments"
        )

        response = requests.post(url, headers=self._get_request_headers, json=payload)

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

    def _check_pull_request_title(self) -> None:
        """Check if changelog should be generated for this pull request"""
        pull_request_title = self.event_payload["pull_request"]["title"]
        pattern = re.compile(self.config.pull_request_title_regex)
        match = pattern.search(pull_request_title)

        if not match:
            # if pull request regex doesn't match then exit
            # and don't generate changelog
            gha_utils.error(
                f"The title of the pull request did not match. "
                f'Regex tried: "{self.config.pull_request_title_regex}", '
                f"Aborting Changelog Generation."
            )
            raise SystemExit(0)

    def _get_release_version(self) -> str:
        """Get release version number from the pull request title"""
        pull_request_title = self.event_payload["pull_request"]["title"]
        pattern = re.compile(self.config.version_regex)
        match = pattern.search(pull_request_title)

        if match:
            return match.group()

        # if the pull request title is not valid, exit the method
        # It might happen if the pull request is not meant to be release
        # or the title was not accurate.
        gha_utils.error(
            f"Could not find matching version number from pull request title. "
            f"Regex tried: {self.config.version_regex} "
            f"Aborting Changelog Generation"
        )
        raise SystemExit(0)

    @property
    def _commit_branch_name(self) -> str:
        """Get the name of the branch to commit the changelog to"""
        return self.action_env.pull_request_branch

    def _get_changes_after_last_release(self) -> list[dict[str, str | int | list[str]]]:
        """Get all the merged pull request after latest release"""
        previous_release_date = self._get_latest_release_date()

        if previous_release_date:
            merged_date_filter = "merged:>=" + previous_release_date
        else:
            # if there is no release for the repo then
            # do not filter by merged date
            merged_date_filter = ""

        # Detail on the GitHub Search API:
        # https://docs.github.com/en/rest/search#search-issues-and-pull-requests
        # https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests
        # https://docs.github.com/en/search-github/getting-started-with-searching-on-github/sorting-search-results
        url = (
            f"{self.GITHUB_API_URL}/search/issues"
            f"?q=repo:{self.action_env.repository}+"
            "is:pr+"
            "is:merged+"
            "sort:created-asc+"
            f"{merged_date_filter}"
            "&per_page=100"
        )

        items = []

        response = requests.get(url, headers=self._get_request_headers)

        if response.status_code == 200:
            response_data = response.json()

            # `total_count` represents the number of
            # pull requests returned by the API call
            if response_data["total_count"] > 0:
                for item in response_data["items"]:
                    data = {
                        "title": item["title"],
                        "number": item["number"],
                        "url": item["html_url"],
                        "labels": [label["name"] for label in item["labels"]],
                    }
                    items.append(data)
            else:
                gha_utils.error(
                    f"There was no pull request "
                    f"made on {self.action_env.repository} after last release."
                )
        else:
            gha_utils.error(
                f"Could not get pull requests for "
                f"{self.action_env.repository} from GitHub API. "
                f"response status code: {response.status_code}"
            )
        return items

    @lru_cache
    def _parse_changelog(self, file_type: str) -> str:
        """Parse the pull requests data and return a string (Markdown or ReStructuredText)"""
        new_changes = copy.deepcopy(self.change_list)
        header = f"{self.config.header_prefix} {self.release_version}"

        if file_type == MARKDOWN_FILE:
            changelog_string = f"# {header}\n\n"
        else:
            changelog_string = f"{header}\n{'=' * len(header)}\n\n"

        group_config = self.config.group_config

        if group_config:
            for config in group_config:

                if len(new_changes) == 0:
                    break

                items_string = ""

                pull_request_list = copy.deepcopy(new_changes)

                for pull_request in pull_request_list:
                    # check if the pull request label matches with
                    # any label of the config
                    if any(
                        label in pull_request["labels"] for label in config["labels"]
                    ):
                        items_string += self._get_changelog_line(
                            file_type, pull_request
                        )
                        # remove the item so that one item
                        # does not match multiple groups
                        new_changes.remove(pull_request)

                if items_string:
                    if file_type == MARKDOWN_FILE:
                        changelog_string += f"\n#### {config['title']}\n\n"
                    else:
                        changelog_string += (
                            f"\n{config['title']}\n {'-' * len(config['title'])}\n\n"
                        )
                    changelog_string += items_string

            if new_changes and self.config.include_unlabeled_changes:
                # if they do not match any user provided group
                # Add items in `unlabeled group` group
                if file_type == MARKDOWN_FILE:
                    changelog_string += (
                        f"\n#### {self.config.unlabeled_group_title}\n\n"
                    )
                else:
                    changelog_string += (
                        f"\n{self.config.unlabeled_group_title}\n"
                        f"{'-' * len(self.config.unlabeled_group_title)}\n\n"
                    )
                changelog_string += "".join(
                    [self._get_changelog_line(file_type, item) for item in new_changes]
                )
        else:
            # If group config does not exist then append it without and groups
            changelog_string += "".join(
                [self._get_changelog_line(file_type, item) for item in new_changes]
            )

        return changelog_string


class ChangelogCICommitMessage(ChangelogCIBase):
    """Generates, commits and/or comments changelog using commit messages"""

    @staticmethod
    def _get_changelog_line(file_type: str, item: dict[str, Any]) -> str:
        """Generate each line of changelog"""
        if file_type == MARKDOWN_FILE:
            changelog_line_template = "* [{sha}]({url}): {message}\n"
        else:
            changelog_line_template = "* `{sha} <{url}>`__: {message}\n"

        return changelog_line_template.format(
            sha=item["sha"][:7], url=item["url"], message=item["message"]
        )

    def _comment_changelog(self, changelog_string: str) -> None:
        """Comment changelog on GitHub"""
        gha_utils.error(
            "`comment_changelog` can only be used "
            "if Changelog CI is triggered on a pull request. "
            "Please Check the Documentation for more details."
        )

    def _create_new_branch(self) -> str:
        """Creates a new branch"""
        # Use timestamp to ensure uniqueness of the new branch
        new_branch = f"changelog-ci-{self.release_version}-{int(time.time())}"
        create_new_git_branch(self.action_env.base_branch, new_branch)
        return new_branch

    @property
    def _commit_branch_name(self) -> str:
        """Get the name of the branch to commit the changelog to"""
        return self._create_new_branch()

    def _commit_changelog(self, commit_branch_name: str) -> None:
        """Commits the changelog to the new branch and creates a pull request"""
        super()._commit_changelog(commit_branch_name)

        if self.config.changelog_file_type == RESTRUCTUREDTEXT_FILE:
            markdown_changelog_string = self._parse_changelog(MARKDOWN_FILE)
        else:
            markdown_changelog_string = self.changelog_string

        with gha_utils.group("Create Pull Request"):
            self._create_pull_request(commit_branch_name, markdown_changelog_string)

    def _get_release_version(self) -> str:
        """Returns the release version"""
        release_version = self.config.release_version

        if not release_version:
            gha_utils.error(
                "`release_version` input must be provided to generate Changelog. "
                "Please Check the Documentation for more details. "
                "Aborting Changelog Generation"
            )
            raise SystemExit(1)

        return release_version

    def _get_changes_after_last_release(self) -> list[dict[str, str]]:
        """Get all the merged pull request after latest release"""
        # Detail on the GitHub Commits API:
        # https://docs.github.com/en/rest/commits/commits#list-commits
        url = f"{self.GITHUB_API_URL}/repos/{self.action_env.repository}/commits?per_page=100"
        previous_release_date = self._get_latest_release_date()

        if previous_release_date:
            url = f"{url}&since={previous_release_date}"

        items = []

        response = requests.get(url, headers=self._get_request_headers)

        if response.status_code == 200:
            response_data = response.json()

            if len(response_data) > 0:
                for item in response_data:
                    message = item["commit"]["message"]
                    # Exclude merge commit
                    if not (
                        message.startswith("Merge pull request #")
                        or message.startswith("Merge branch")
                    ):
                        data = {
                            "sha": item["sha"],
                            "message": message,
                            "url": item["html_url"],
                        }
                        items.append(data)
                    else:
                        gha_utils.notice(f'Skipping Merge Commit "{message}"')
            else:
                gha_utils.error(
                    f"There was no commit "
                    f"made on {self.action_env.repository} after last release."
                )
        else:
            gha_utils.error(
                f"Could not get commits for "
                f"{self.action_env.repository} from GitHub API. "
                f"response status code: {response.status_code}"
            )
        return items

    @lru_cache
    def _parse_changelog(self, file_type: str) -> str:
        """Parse the commit data and return a string (Markdown or ReStructuredText)"""
        new_changes = copy.deepcopy(self.change_list)
        header = f"{self.config.header_prefix} {self.release_version}"

        if file_type == MARKDOWN_FILE:
            changelog_string = f"# {header}\n\n"
        else:
            changelog_string = f"{header}\n{'=' * len(header)}\n\n"
        changelog_string += "".join(
            [self._get_changelog_line(file_type, item) for item in new_changes]
        )

        return changelog_string


CHANGELOG_CI_CLASSES = {
    PULL_REQUEST: ChangelogCIPullRequest,
    COMMIT_MESSAGE: ChangelogCICommitMessage,
}


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
        changelog_ci_class = CHANGELOG_CI_CLASSES[user_configuration.changelog_type]
        # Initialize the Changelog CI
        ci = changelog_ci_class(user_configuration, action_environment)
        # Run Changelog CI
        ci.run()

    display_whats_new()
