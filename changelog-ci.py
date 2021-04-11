import json
import os
import re
import subprocess
from functools import cached_property

import requests
import yaml

# The regular expression used to extract semantic versioning is a
# slightly less restrictive modification of the following regular expression
# https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
DEFAULT_SEMVER_REGEX = (
    r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-(("
    r"?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|["
    r"1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(["
    r"0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
)
DEFAULT_PULL_REQUEST_TITLE_REGEX = r"^(?i:release)"
DEFAULT_VERSION_PREFIX = "Version:"
DEFAULT_GROUP_CONFIG = []

# Changelog types
PULL_REQUEST = 'pull_request'
COMMIT = 'commit_message'

DEFAULT_CONFIG = {
    "header_prefix": DEFAULT_VERSION_PREFIX,
    "commit_changelog": True,
    "comment_changelog": False,
    "pull_request_title_regex": DEFAULT_PULL_REQUEST_TITLE_REGEX,
    "version_regex": DEFAULT_SEMVER_REGEX,
    "group_config": DEFAULT_GROUP_CONFIG,
    "changelog_type": PULL_REQUEST
}


class ChangelogCIBase:
    """The class that generates, commits and/or comments changelog"""

    github_api_url = 'https://api.github.com'

    def __init__(
        self,
        repository,
        event_path,
        config,
        filename='CHANGELOG.md',
        token=None
    ):
        self.repository = repository
        self.filename = filename
        self.config = config
        self.token = token

        title, number = self._get_pull_request_title_and_number(event_path)
        self.pull_request_title = title
        self.pull_request_number = number

    @staticmethod
    def _get_pull_request_title_and_number(event_path):
        """Gets pull request title from `GITHUB_EVENT_PATH`"""
        with open(event_path, 'r') as json_file:
            # This is just a webhook payload available to the Action
            data = json.load(json_file)
            title = data["pull_request"]['title']
            number = data['number']

        return title, number

    @cached_property
    def _get_request_headers(self):
        """Get headers for GitHub API request"""
        headers = {
            'Accept': 'application/vnd.github.v3+json'
        }
        # if the user adds `GITHUB_TOKEN` add it to API Request
        # required for `private` repositories
        if self.token:
            headers.update({
                'authorization': 'Bearer {token}'.format(token=self.token)
            })

        return headers

    def get_changes_after_last_release(self):
        return NotImplemented

    def parse_changelog(self, version, changes):
        return NotImplemented

    def _validate_pull_request(self):
        """Check if changelog should be generated for this pull request"""
        pattern = re.compile(self.config['pull_request_title_regex'])
        match = pattern.search(self.pull_request_title)

        if match:
            return True

        return

    def _get_version_number(self):
        """Get version number from the pull request title"""
        pattern = re.compile(self.config['version_regex'])
        match = pattern.search(self.pull_request_title)

        if match:
            return match.group()

        return

    def _get_file_mode(self):
        """Gets the mode that the changelog file should be opened in"""
        if os.path.exists(self.filename):
            # if the changelog file exists
            # opens it in read-write mode
            file_mode = 'r+'
        else:
            # if the changelog file does not exists
            # opens it in read-write mode
            # but creates the file first also
            file_mode = 'w+'

        return file_mode

    def _get_latest_release_date(self):
        """Using GitHub API gets latest release date"""
        url = (
            '{base_url}/repos/{repo_name}/releases/latest'
        ).format(
            base_url=self.github_api_url,
            repo_name=self.repository
        )

        response = requests.get(url, headers=self._get_request_headers)

        published_date = ''

        if response.status_code == 200:
            response_data = response.json()
            # get the published date of the latest release
            published_date = response_data['published_at']
        else:
            # if there is no previous release API will return 404 Not Found
            msg = (
                f'Could not find any previous release for '
                f'{self.repository}, status code: {response.status_code}'
            )
            print_message(msg, message_type='warning')

        return published_date

    def _commit_changelog(self, string_data):
        """Write changelog to the changelog file"""
        file_mode = self._get_file_mode()

        with open(self.filename, file_mode) as f:
            # read the existing data and store it in a variable
            body = f.read()
            # write at the top of the file
            f.seek(0, 0)
            f.write(string_data)

            if body:
                # re-write the existing data
                f.write('\n\n')
                f.write(body)

        subprocess.run(['git', 'add', self.filename])
        subprocess.run(
            ['git', 'commit', '-m', '(Changelog CI) Added Changelog']
        )
        subprocess.run(['git', 'push', '-u', 'origin', ref])

    def _comment_changelog(self, string_data):
        """Comments Changelog to the pull request"""
        if not self.token:
            # Token is required by the GitHub API to create a Comment
            # if not provided exit with error message
            msg = (
                "Could not add a comment. "
                "`GITHUB_TOKEN` is required for this operation. "
                "If you want to enable Changelog comment, please add "
                "`GITHUB_TOKEN` to your workflow yaml file. "
                "Look at Changelog CI's documentation for more information."
            )

            print_message(msg, message_type='error')
            return

        owner, repo = self.repository.split('/')

        payload = {
            'owner': owner,
            'repo': repo,
            'issue_number': self.pull_request_number,
            'body': string_data
        }

        url = (
            '{base_url}/repos/{repo}/issues/{number}/comments'
        ).format(
            base_url=self.github_api_url,
            repo=self.repository,
            number=self.pull_request_number
        )

        response = requests.post(
            url, headers=self._get_request_headers, json=payload
        )

        if response.status_code != 201:
            # API should return 201, otherwise show error message
            msg = (
                f'Error while trying to create a comment. '
                f'GitHub API returned error response for '
                f'{self.repository}, status code: {response.status_code}'
            )

            print_message(msg, message_type='error')

    def run(self):
        """Entrypoint to the Changelog CI"""
        if (
            not self.config['commit_changelog'] and
            not self.config['comment_changelog']
        ):
            # if both commit_changelog and comment_changelog is set to false
            # then exit with warning and don't generate Changelog
            msg = (
                'Skipping Changelog generation as both `commit_changelog` '
                'and `comment_changelog` is set to False. '
                'If you did not intend to do this please set '
                'one or both of them to True.'
            )
            print_message(msg, message_type='error')
            return

        is_valid_pull_request = self._validate_pull_request()

        if not is_valid_pull_request:
            # if pull request regex doesn't match then exit
            # and don't generate changelog
            msg = (
                f'The title of the pull request did not match. '
                f'Regex tried: "{self.config["pull_request_title_regex"]}", '
                f'Aborting Changelog Generation.'
            )
            print_message(msg, message_type='error')
            return

        version = self._get_version_number()

        if not version:
            # if the pull request title is not valid, exit the method
            # It might happen if the pull request is not meant to be release
            # or the title was not accurate.
            msg = (
                f'Could not find matching version number. '
                f'Regex tried: {self.config["version_regex"]} '
                f'Aborting Changelog Generation'
            )
            print_message(msg, message_type='error')
            return

        changes = self.get_changes_after_last_release()

        # exit the method if there is no changes found
        if not changes:
            return

        string_data = self.parse_changelog(version, changes)

        if self.config['commit_changelog']:
            print_message('Commit Changelog', message_type='group')
            self._commit_changelog(string_data)
            print_message('', message_type='endgroup')

        if self.config['comment_changelog']:
            print_message('Comment Changelog', message_type='group')
            self._comment_changelog(string_data)
            print_message('', message_type='endgroup')


class ChangelogCIPullRequest(ChangelogCIBase):
    """The class that generates, commits and/or comments changelog using pull requests"""

    github_api_url = 'https://api.github.com'

    @staticmethod
    def _get_changelog_line(item):
        """Generate each line of changelog"""
        return "* [#{number}]({url}): {title}\n".format(
            number=item['number'],
            url=item['url'],
            title=item['title']
        )

    def get_changes_after_last_release(self):
        """Get all the merged pull request after latest release"""
        previous_release_date = self._get_latest_release_date()

        if previous_release_date:
            merged_date_filter = 'merged:>=' + previous_release_date
        else:
            # if there is no release for the repo then
            # do not filter by merged date
            merged_date_filter = ''

        url = (
            '{base_url}/search/issues'
            '?q=repo:{repo_name}+'
            'is:pr+'
            'is:merged+'
            'sort:author-date-asc+'
            '{merged_date_filter}'
            '&sort=merged'
        ).format(
            base_url=self.github_api_url,
            repo_name=self.repository,
            merged_date_filter=merged_date_filter
        )

        items = []

        response = requests.get(url, headers=self._get_request_headers)

        if response.status_code == 200:
            response_data = response.json()

            # `total_count` represents the number of
            # pull requests returned by the API call
            if response_data['total_count'] > 0:
                for item in response_data['items']:
                    data = {
                        'title': item['title'],
                        'number': item['number'],
                        'url': item['html_url'],
                        'labels': [label['name'] for label in item['labels']]
                    }
                    items.append(data)
            else:
                msg = (
                    f'There was no pull request '
                    f'made on {self.repository} after last release.'
                )
                print_message(msg, message_type='error')
        else:
            msg = (
                f'Could not get pull requests for '
                f'{self.repository} from GitHub API. '
                f'response status code: {response.status_code}'
            )
            print_message(msg, message_type='error')

        return items

    def parse_changelog(self, version, changes):
        """Parse the pull requests data and return a string"""
        string_data = (
            '# ' + self.config['header_prefix'] + ' ' + version + '\n\n'
        )

        group_config = self.config['group_config']

        if group_config:
            for config in group_config:

                if len(changes) == 0:
                    break

                items_string = ''

                for pull_request in changes:
                    # check if the pull request label matches with
                    # any label of the config
                    if (
                        any(
                            label in pull_request['labels']
                            for label in config['labels']
                        )
                    ):
                        items_string += self._get_changelog_line(pull_request)
                        # remove the item so that one item
                        # does not match multiple groups
                        changes.remove(pull_request)

                if items_string:
                    string_data += '\n#### ' + config['title'] + '\n\n'
                    string_data += '\n' + items_string

            if changes:
                # if they do not match any user provided group
                # Add items in `Other Changes` group
                string_data += '\n#### Other Changes\n\n'
                string_data += ''.join(
                    map(self._get_changelog_line, changes)
                )
        else:
            # If group config does not exist then append it without and groups
            string_data += ''.join(
                map(self._get_changelog_line, changes)
            )

        return string_data


class ChangelogCICommitMessage(ChangelogCIBase):
    """The class that generates, commits and/or comments changelog using commit messages"""

    @staticmethod
    def _get_changelog_line(item):
        """Generate each line of changelog"""
        return "* [{sha}]({url}): {message}\n".format(
            sha=item['sha'][:6],
            url=item['url'],
            message=item['message']
        )

    def get_changes_after_last_release(self):
        """Get all the merged pull request after latest release"""
        previous_release_date = self._get_latest_release_date()

        url = '{base_url}/repos/{repo_name}/commits?since={date}'.format(
            base_url=self.github_api_url,
            repo_name=self.repository,
            date=previous_release_date or ''
        )

        items = []

        response = requests.get(url, headers=self._get_request_headers)

        if response.status_code == 200:
            response_data = response.json()

            if len(response_data) > 0:
                for item in response_data:
                    data = {
                        'sha': item['sha'],
                        'message': item['commit']['message'],
                        'url': item['html_url']
                    }
                    items.append(data)
            else:
                msg = (
                    f'There was no commit '
                    f'made on {self.repository} after last release.'
                )
                print_message(msg, message_type='error')
        else:
            msg = (
                f'Could not get commits for '
                f'{self.repository} from GitHub API. '
                f'response status code: {response.status_code}'
            )
            print_message(msg, message_type='error')

        return items

    def parse_changelog(self, version, changes):
        """Parse the commit data and return a string"""
        string_data = (
            '# ' + self.config['header_prefix'] + ' ' + version + '\n\n'
        )
        string_data += ''.join(map(self._get_changelog_line, changes))

        return string_data


def parse_config(config_file):
    """Parse and Validates user provided config, raises Error if not valid"""
    if not config_file:
        print_message(
            'No Configuration file found, falling back to default configuration',
            message_type='warning'
        )
        return DEFAULT_CONFIG

    try:
        file = open(config_file)
        # parse config files with the extension .yml and .yaml
        # using YAML syntax
        if config_file.endswith('yml') or config_file.endswith('yaml'):
            config = yaml.load(file, Loader=yaml.FullLoader)
        # default to parsing the config file using JSON
        else:
            config = json.load(file)

        file.close()
    except Exception as e:
        msg = (
            f'Invalid Configuration file, error: {e}, '
            'falling back to default configuration to parse changelog'
        )
        print_message(msg, message_type='error')
        # if invalid fall back to default config
        return DEFAULT_CONFIG

    if not isinstance(config, dict):
        raise TypeError(
            'Configuration does not contain required key, value pairs'
        )

    pull_request_title_regex = config.get('pull_request_title_regex')
    version_regex = config.get('version_regex')

    try:
        # if the regex is not provided or is an empty string
        # just raise KeyError and fallback to default
        if not pull_request_title_regex:
            raise KeyError

        # This will raise an error if the provided regex is not valid
        re.compile(pull_request_title_regex)
    except Exception:
        msg = (
            '`pull_request_title_regex` was not provided or not valid, '
            'Falling back to default regex.'
        )
        print_message(msg, message_type='warning')
        # if the pull_request_title_regex is not valid or not available
        # fallback to default regex
        config.update({
            "pull_request_title_regex": DEFAULT_PULL_REQUEST_TITLE_REGEX
        })

    try:
        # if the regex is not provided or is an empty string
        # just raise KeyError and fallback to default
        if not version_regex:
            raise KeyError

        # This will raise an error if the provided regex is not valid
        re.compile(version_regex)
    except Exception:
        msg = (
            '`version_regex` was not provided or not valid, '
            'Falling back to default regex.'
        )
        print_message(msg, message_type='warning')
        # if the version_regex is not valid or not available
        # fallback to default regex
        config.update({
            "version_regex": DEFAULT_SEMVER_REGEX
        })

    try:
        commit_changelog = config['commit_changelog']
        config.update({
            "commit_changelog": bool(commit_changelog)
        })
    except Exception:
        msg = (
            '`commit_changelog` was not provided or not valid, '
            'falling back to `True`.'
        )
        print_message(msg, message_type='warning')
        # if commit_changelog is not provided default to True
        config.update({
            "commit_changelog": True
        })

    try:
        comment_changelog = config['comment_changelog']
        config.update({
            "comment_changelog": bool(comment_changelog)
        })
    except Exception:
        msg = (
            '`comment_changelog` was not provided or not valid, '
            'falling back to `False`.'
        )
        print_message(msg, message_type='warning')
        # if comment_changelog is not provided default to False
        config.update({
            "comment_changelog": False
        })

    header_prefix = config.get('header_prefix')

    if not header_prefix or not isinstance(header_prefix, str):
        msg = (
            '`header_prefix` was not provided or not valid, '
            'falling back to default prefix.'
        )
        print_message(msg, message_type='warning')
        # if the header_prefix is not not available
        # fallback to default prefix
        config.update({
            "header_prefix": DEFAULT_VERSION_PREFIX
        })

    changelog_type = config.get('changelog_type')

    if not (
        changelog_type or
        isinstance(changelog_type, str) or
        changelog_type in [PULL_REQUEST, COMMIT]
    ):
        msg = (
            '`changelog_type` was not provided or not valid, '
            f'the options are {PULL_REQUEST} or {COMMIT}, '
            f'falling back to default value of "{PULL_REQUEST}".'
        )
        print_message(msg, message_type='warning')
        # if changelog_type is not not available
        # fallback to default PULL_REQUEST
        config.update({
            "changelog_type": PULL_REQUEST
        })

    group_config = config.get('group_config')

    if not group_config or not isinstance(group_config, list):
        msg = (
            '`group_config` was not provided or not valid, '
            'falling back to default group config.'
        )
        print_message(msg, message_type='warning')
        # if the group_config is not not available
        # fallback to default group_config
        config.update({
            "group_config": DEFAULT_GROUP_CONFIG
        })
    else:
        try:
            # Check if all the group configs match the schema
            for item in group_config:
                if not isinstance(config, dict):
                    raise TypeError(
                        'group_config items must have key, '
                        'value pairs of title and labels'
                    )
                title = item.get('title')
                labels = item.get('labels')

                if not title:
                    raise KeyError('group_config item must contain title')

                if not labels:
                    raise KeyError('group_config item must contain labels')

                if not isinstance(labels, list):
                    raise TypeError('group_config labels must be an Array')

        except Exception as e:
            msg = (
                f'An error occurred while parsing `group_config`. Error: {e}'
                f'falling back to default group config.'
            )
            print_message(msg, message_type='warning')
            # Fallback to default group_config
            config.update({
                "group_config": DEFAULT_GROUP_CONFIG
            })
    return config


def print_message(message, message_type=None):
    """Helper function to print colorful outputs in GitHub Actions shell"""
    # docs: https://docs.github.com/en/actions/reference/workflow-commands-for-github-actions
    if not message_type:
        return subprocess.run(['echo', f'{message}'])

    if message_type == 'endgroup':
        return subprocess.run(['echo', '::endgroup::'])

    return subprocess.run(['echo', f'::{message_type}::{message}'])


CI_CLASSES = {
    PULL_REQUEST: ChangelogCIPullRequest,
    COMMIT: ChangelogCICommitMessage
}


if __name__ == '__main__':
    # Default environment variable from GitHub
    # https://docs.github.com/en/actions/configuring-and-managing-workflows/using-environment-variables
    event_path = os.environ['GITHUB_EVENT_PATH']
    repository = os.environ['GITHUB_REPOSITORY']
    ref = os.environ['GITHUB_HEAD_REF']
    # User inputs from workflow
    filename = os.environ['INPUT_CHANGELOG_FILENAME']
    config_file = os.environ['INPUT_CONFIG_FILE']
    # Token provided from the workflow
    token = os.environ.get('GITHUB_TOKEN')
    # Committer username and email address
    username = os.environ['INPUT_COMMITTER_USERNAME']
    email = os.environ['INPUT_COMMITTER_EMAIL']

    # Group: Checkout git repository
    print_message('Checkout git repository', message_type='group')


    subprocess.run(['git', 'fetch', '--prune', '--unshallow', 'origin', ref])
    subprocess.run(['git', 'checkout', ref])

    print_message('', message_type='endgroup')

    # Group: Configure Git
    print_message('Configure Git', message_type='group')

    subprocess.run(['git', 'config', 'user.name', username])
    subprocess.run(['git', 'config', 'user.email', email])

    print_message('', message_type='endgroup')

    print_message('Parse Configuration', message_type='group')

    config = parse_config(config_file)

    print_message('', message_type='endgroup')

    # Group: Generate Changelog
    print_message('Generate Changelog', message_type='group')
    # Get CI class using configuration
    changelog_ci_class = CI_CLASSES.get(
        config['generate_changelog_using']
    )
    # Initialize the Changelog CI
    ci = changelog_ci_class(
        repository,
        event_path,
        config,
        filename=filename,
        token=token
    )
    # Run Changelog CI
    ci.run()

    print_message('', message_type='endgroup')
