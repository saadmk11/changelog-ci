import copy
from functools import lru_cache
from typing import Any

import github_action_utils as gha_utils  # type: ignore
import requests

from .config import MARKDOWN_FILE, ActionEnvironment, Configuration
from .utils import get_request_headers


class ChangelogBuilderBase:
    """Base Class for Changelog Builder"""

    GITHUB_API_URL: str = "https://api.github.com"

    def __init__(
        self,
        config: Configuration,
        action_env: ActionEnvironment,
        release_version: object,
    ) -> None:
        self.config = config
        self.action_env = action_env
        self.release_version = release_version

        self.changelog_string = ""
        self.change_list: list[dict[str, Any]] = []

    @staticmethod
    def _get_changelog_line(file_type: str, item: dict[str, Any]) -> str:
        """Generate each line of the changelog"""
        raise NotImplementedError

    def _get_changes_after_last_release(self) -> list[dict[str, Any]]:
        """Get changes list after last release"""
        raise NotImplementedError

    @lru_cache
    def parse_changelog(self, file_type: str) -> str:
        """Parse changelog, and build the changelog string (Markdown or ReStructuredText)"""
        raise NotImplementedError

    def _get_latest_release_date(self) -> str:
        """Using GitHub API gets the latest release date"""
        url = (
            f"{self.GITHUB_API_URL}/repos/"
            f"{self.action_env.repository}/releases/latest"
        )

        response = requests.get(
            url, headers=get_request_headers(self.config.github_token)
        )

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

    def build(self) -> str:
        """Generate the changelog"""
        self.change_list = self._get_changes_after_last_release()

        # exit the method if there is no changes found
        if not self.change_list:
            raise SystemExit(0)

        self.changelog_string = self.parse_changelog(self.config.changelog_file_type)

        return self.changelog_string


class PullRequestChangelogBuilder(ChangelogBuilderBase):
    """Changelog Builder that Uses Pull Request Titles to Generate the Changelog"""

    @staticmethod
    def _get_changelog_line(file_type: str, item: dict[str, Any]) -> str:
        """Generate each line of the changelog"""
        if file_type == MARKDOWN_FILE:
            changelog_line_template = "* [#{number}]({url}): {title}\n"
        else:
            changelog_line_template = "* `#{number} <{url}>`__: {title}\n"

        return changelog_line_template.format(
            number=item["number"], url=item["url"], title=item["title"]
        )

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

        response = requests.get(
            url, headers=get_request_headers(self.config.github_token)
        )

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
    def parse_changelog(self, file_type: str) -> str:
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


class CommitMessageChangelogBuilder(ChangelogBuilderBase):
    """Changelog Builder that Uses Commit Messages to Generate the Changelog"""

    @staticmethod
    def _get_changelog_line(file_type: str, item: dict[str, Any]) -> str:
        """Generate each line of the changelog"""
        if file_type == MARKDOWN_FILE:
            changelog_line_template = "* [{sha}]({url}): {message}\n"
        else:
            changelog_line_template = "* `{sha} <{url}>`__: {message}\n"

        return changelog_line_template.format(
            sha=item["sha"][:7], url=item["url"], message=item["message"]
        )

    def _get_changes_after_last_release(self) -> list[dict[str, str]]:
        """Get all the merged pull request after latest release"""
        # Detail on the GitHub Commits API:
        # https://docs.github.com/en/rest/commits/commits#list-commits
        url = f"{self.GITHUB_API_URL}/repos/{self.action_env.repository}/commits?per_page=100"
        previous_release_date = self._get_latest_release_date()

        if previous_release_date:
            url = f"{url}&since={previous_release_date}"

        items = []

        response = requests.get(
            url, headers=get_request_headers(self.config.github_token)
        )

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
    def parse_changelog(self, file_type: str) -> str:
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
