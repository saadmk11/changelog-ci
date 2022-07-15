import copy
import os
import re
import time
from typing import Type

import requests

from .config import (
    ActionEnvironment,
    COMMIT_MESSAGE,
    Configuration,
    MARKDOWN_FILE,
    PULL_REQUEST,
    RESTRUCTUREDTEXT_FILE,
)
from .run_git import (
    checkout_pull_request_branch,
    configure_git_author,
    create_new_git_branch,
    git_commit_changelog,
)
from .utils import print_message, display_whats_new


class ChangelogCIBase:
    """Base Class for Changelog CI"""

    GITHUB_API_URL: str = "https://api.github.com"

    WORKFLOW_DISPATCH_EVENT: str = "workflow_dispatch"
    PULL_REQUEST_EVENT: str = "pull_request"

    def __init__(self, config: Configuration, action_env: ActionEnvironment) -> None:
        self.config = config
        self.action_env = action_env
        self.release_version = self.config.release_version

    @property
    def _get_request_headers(self) -> dict[str, str]:
        """Get headers for GitHub API request"""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.config.github_token:
            headers.update({"authorization": f"Bearer {self.config.github_token}"})

        return headers

    def _create_new_branch(self) -> str:
        """Create and push a new branch with the changes"""
        # Use timestamp to ensure uniqueness of the new branch
        new_branch = f"changelog-ci-{self.release_version}-{int(time.time())}"

        create_new_git_branch(self.action_env.base_branch, new_branch)
        self._commit_changelog(new_branch)

        return new_branch

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
            print_message(f"Pull request opened at {html_url} \U0001F389")
        else:
            msg = (
                f"Could not create a pull request on "
                f"{self.action_env.repository}, status code: {response.status_code}"
            )
            print_message(msg, message_type="error")

    def _validate_pull_request_title(self, pull_request_title: str) -> bool:
        """Check if changelog should be generated for this pull request"""
        pattern = re.compile(self.config.pull_request_title_regex)
        match = pattern.search(pull_request_title)

        if match:
            return True
        return False

    def _set_release_version_from_pull_request_title(
        self, pull_request_title: str
    ) -> None:
        """Get version number from the pull request title"""
        pattern = re.compile(self.config.version_regex)
        match = pattern.search(pull_request_title)

        if match:
            self.release_version = match.group()

    def _get_file_mode(self) -> str:
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
            msg = (
                f"Could not find any previous release for "
                f"{self.action_env.repository}, status code: {response.status_code}"
            )
            print_message(msg, message_type="warning")

        return published_date

    def _update_changelog_file(self, string_data: str) -> None:
        """Write changelog to the changelog file"""
        file_mode = self._get_file_mode()

        with open(self.config.changelog_filename, file_mode) as f:
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

    def _comment_changelog(
        self, string_data: str, pull_request_number: int | None
    ) -> None:
        """Comments Changelog to the pull request"""
        if not self.config.github_token:
            # Token is required by the GitHub API to create a Comment
            # if not provided exit with error message
            msg = (
                "Could not add a comment. "
                "`github_token` input is required for this operation. "
                "If you want to enable Changelog comment, please add "
                "`github_token` to your workflow yaml file. "
                "Look at Changelog CI's documentation for more information."
            )

            print_message(msg, message_type="error")
            return

        owner, repo = self.action_env.repository.split("/")

        payload = {
            "owner": owner,
            "repo": repo,
            "issue_number": pull_request_number,
            "body": string_data,
        }

        url = (
            f"{self.GITHUB_API_URL}/repos/{self.action_env.repository}/"
            f"issues/{pull_request_number}/comments"
        )

        response = requests.post(url, headers=self._get_request_headers, json=payload)

        if response.status_code != 201:
            # API should return 201, otherwise show error message
            msg = (
                f"Error while trying to create a comment. "
                f"GitHub API returned error response for "
                f"{self.action_env.repository}, status code: {response.status_code}"
            )

            print_message(msg, message_type="warning")
        else:
            print_message(f"Comment added at {response.json()['html_url']} \U0001F389")

    def get_changes_after_last_release(self):
        raise NotImplementedError

    def parse_changelog(self, file_type: str, version: str, changes: list):
        raise NotImplementedError

    def run(self) -> None:
        """Entrypoint to the Changelog CI"""
        if not self.config.commit_changelog and not self.config.comment_changelog:
            # if both commit_changelog and comment_changelog is set to false
            # then exit with warning and don't generate Changelog
            msg = (
                "Skipping Changelog generation as both `commit_changelog` "
                "and `comment_changelog` is set to False. "
                "If you did not intend to do this please set "
                "one or both of them to True."
            )
            print_message(msg, message_type="error")
            return

        if (
            not self.action_env.event_name == self.PULL_REQUEST_EVENT
            and not self.release_version
        ):
            msg = (
                "Skipping Changelog generation. "
                "Changelog CI could not find the Release Version. "
                "Changelog CI should be triggered on a pull request or "
                "`release_version` input must be provided on the workflow. "
                "Please Check the Documentation for more details."
            )
            print_message(msg, message_type="error")
            return

        pull_request_number = None

        if self.action_env.event_name == self.PULL_REQUEST_EVENT:
            event_payload = self.action_env.event_payload
            pull_request_title = event_payload["pull_request"]["title"]
            pull_request_number = event_payload["number"]

            if not self._validate_pull_request_title(pull_request_title):
                # if pull request regex doesn't match then exit
                # and don't generate changelog
                msg = (
                    f"The title of the pull request did not match. "
                    f'Regex tried: "{self.config.pull_request_title_regex}", '
                    f"Aborting Changelog Generation."
                )
                print_message(msg, message_type="error")
                return

            self._set_release_version_from_pull_request_title(
                pull_request_title=pull_request_title
            )

        if not self.release_version:
            # if the pull request title is not valid, exit the method
            # It might happen if the pull request is not meant to be release
            # or the title was not accurate.
            if self.action_env.event_name == self.PULL_REQUEST_EVENT:
                msg = (
                    f"Could not find matching version number from pull request title. "
                    f"Regex tried: {self.config.version_regex} "
                    f"Aborting Changelog Generation"
                )
            else:
                msg = (
                    "`release_version` input must be provided to generate Changelog. "
                    "Please Check the Documentation for more details. "
                    "Aborting Changelog Generation"
                )
            print_message(msg, message_type="error")
            return

        changes = self.get_changes_after_last_release()

        # exit the method if there is no changes found
        if not changes:
            return

        string_data = self.parse_changelog(
            self.config.changelog_file_type, self.release_version, changes
        )
        markdown_string_data = string_data

        if all(
            [
                self.config.comment_changelog
                or self.action_env.event_name != self.PULL_REQUEST_EVENT,
                self.config.changelog_file_type == RESTRUCTUREDTEXT_FILE,
            ]
        ):
            markdown_string_data = self.parse_changelog(
                MARKDOWN_FILE, self.release_version, changes
            )

        if self.config.commit_changelog:
            self._update_changelog_file(string_data)
            if self.action_env.event_name == self.PULL_REQUEST_EVENT:
                print_message("Commit Changelog", message_type="group")
                self._commit_changelog(self.action_env.pull_request_branch)
                print_message("", message_type="endgroup")
            else:
                print_message("Create New Branch", message_type="group")
                new_branch = self._create_new_branch()
                print_message("", message_type="endgroup")

                print_message("Create Pull Request", message_type="group")
                self._create_pull_request(new_branch, markdown_string_data)
                print_message("", message_type="endgroup")

        if self.config.comment_changelog:
            print_message("Comment Changelog", message_type="group")

            if not self.action_env.event_name == self.PULL_REQUEST_EVENT:
                msg = (
                    "`comment_changelog` can only be used if Changelog CI is triggered on a pull request. "
                    "Please Check the Documentation for more details."
                )
                print_message(msg, message_type="error")
            else:
                self._comment_changelog(markdown_string_data, pull_request_number)
            print_message("", message_type="endgroup")


class ChangelogCIPullRequest(ChangelogCIBase):
    """Generates, commits and/or comments changelog using pull requests"""

    @staticmethod
    def _get_changelog_line(file_type: str, item: dict) -> str:
        """Generate each line of changelog"""
        if file_type == MARKDOWN_FILE:
            changelog_line_template = "* [#{number}]({url}): {title}\n"
        else:
            changelog_line_template = "* `#{number} <{url}>`__: {title}\n"

        return changelog_line_template.format(
            number=item["number"], url=item["url"], title=item["title"]
        )

    def get_changes_after_last_release(self) -> list[dict[str, str | int | list[str]]]:
        """Get all the merged pull request after latest release"""
        previous_release_date = self._get_latest_release_date()

        if previous_release_date:
            merged_date_filter = "merged:>=" + previous_release_date
        else:
            # if there is no release for the repo then
            # do not filter by merged date
            merged_date_filter = ""

        # Detail on the GitHubSearch API:
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
                msg = (
                    f"There was no pull request "
                    f"made on {self.action_env.repository} after last release."
                )
                print_message(msg, message_type="error")
        else:
            msg = (
                f"Could not get pull requests for "
                f"{self.action_env.repository} from GitHub API. "
                f"response status code: {response.status_code}"
            )
            print_message(msg, message_type="error")

        return items

    def parse_changelog(self, file_type: str, version: str, changes: list) -> str:
        """Parse the pull requests data and return a string"""
        new_changes = copy.deepcopy(changes)
        header = f"{self.config.header_prefix} {version}"

        if file_type == MARKDOWN_FILE:
            string_data = f"# {header}\n\n"
        else:
            string_data = f"{header}\n{'=' * len(header)}\n\n"

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
                        string_data += f"\n#### {config['title']}\n\n"
                    else:
                        string_data += (
                            f"\n{config['title']}\n {'-' * len(config['title'])}\n\n"
                        )
                    string_data += items_string

            if new_changes and self.config.include_unlabeled_changes:
                # if they do not match any user provided group
                # Add items in `unlabeled group` group
                if file_type == MARKDOWN_FILE:
                    string_data += f"\n#### {self.config.unlabeled_group_title}\n\n"
                else:
                    string_data += (
                        f"\n{self.config.unlabeled_group_title}\n"
                        f"{'-' * len(self.config.unlabeled_group_title)}\n\n"
                    )
                string_data += "".join(
                    [self._get_changelog_line(file_type, item) for item in new_changes]
                )
        else:
            # If group config does not exist then append it without and groups
            string_data += "".join(
                [self._get_changelog_line(file_type, item) for item in new_changes]
            )

        return string_data


class ChangelogCICommitMessage(ChangelogCIBase):
    """Generates, commits and/or comments changelog using commit messages"""

    @staticmethod
    def _get_changelog_line(file_type: str, item: dict) -> str:
        """Generate each line of changelog"""
        if file_type == MARKDOWN_FILE:
            changelog_line_template = "* [{sha}]({url}): {message}\n"
        else:
            changelog_line_template = "* `{sha} <{url}>`__: {message}\n"

        return changelog_line_template.format(
            sha=item["sha"][:7], url=item["url"], message=item["message"]
        )

    def get_changes_after_last_release(self) -> list[dict[str, str]]:
        """Get all the merged pull request after latest release"""
        url = f"{self.GITHUB_API_URL}/repos/" f"{self.action_env.repository}/commits"
        previous_release_date = self._get_latest_release_date()

        if previous_release_date:
            url = f"{url}?since={previous_release_date}"

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
                        print_message(f'Skipping Merge Commit "{message}"')
            else:
                msg = (
                    f"There was no commit "
                    f"made on {self.action_env.repository} after last release."
                )
                print_message(msg, message_type="error")
        else:
            msg = (
                f"Could not get commits for "
                f"{self.action_env.repository} from GitHub API. "
                f"response status code: {response.status_code}"
            )
            print_message(msg, message_type="error")

        return items

    def parse_changelog(self, file_type: str, version: str, changes: list) -> str:
        """Parse the commit data and return a string"""
        new_changes = copy.deepcopy(changes)
        header = f"{self.config.header_prefix} {version}"

        if file_type == MARKDOWN_FILE:
            string_data = f"# {header}\n\n"
        else:
            string_data = f"{header}\n{'=' * len(header)}\n\n"
        string_data += "".join(
            [self._get_changelog_line(file_type, item) for item in new_changes]
        )

        return string_data


CHANGELOG_CI_CLASSES = {
    PULL_REQUEST: ChangelogCIPullRequest,
    COMMIT_MESSAGE: ChangelogCICommitMessage,
}


if __name__ == "__main__":
    print_message("Parse Configuration", message_type="group")
    user_configuration = Configuration.create(os.environ)
    action_environment = ActionEnvironment.from_env(os.environ)
    print_message("", message_type="endgroup")

    if action_environment.pull_request_branch:
        # Group: Checkout git pull request branch
        print_message(
            f'Checkout "{action_environment.pull_request_branch}" branch',
            message_type="group",
        )
        checkout_pull_request_branch(action_environment.pull_request_branch)
        print_message("", message_type="endgroup")

    # Group: Configure Git Author
    print_message("Configure Git Author", message_type="group")
    configure_git_author(
        user_configuration.git_committer_username,
        user_configuration.git_committer_email,
    )
    print_message(
        f"Setting Git Commit Author to {user_configuration.git_commit_author}."
    )
    print_message("", message_type="endgroup")

    # Group: Generate Changelog
    print_message("Generate Changelog", message_type="group")
    # Get CI class using configuration
    changelog_ci_class: Type[ChangelogCIBase] = CHANGELOG_CI_CLASSES[
        user_configuration.changelog_type
    ]
    # Initialize the Changelog CI
    ci = changelog_ci_class(user_configuration, action_environment)
    # Run Changelog CI
    ci.run()
    print_message("", message_type="endgroup")

    display_whats_new()
