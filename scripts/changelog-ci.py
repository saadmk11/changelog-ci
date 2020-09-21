import json
import logging
import re
import os

import requests


logger = logging.getLogger(__name__)


# Regex is taken from https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
# It was modified a little bit to make it a bit less restrictive
DEFAULT_SEMVER_REGEX = r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
DEFAULT_PULL_REQUEST_TITLE_REGEX = r"^(?i:release)"
DEFAULT_VERSION_PREFIX = "Version:"
DEFAULT_GROUP_CONFIG = []


class ChangelogCI:

    def __init__(
        self, repository,
        event_path, filename='CHANGELOG.md',
        config_file=None, token=None
    ):
        self.repository = repository
        self.filename = filename
        self.config = self._parse_config(config_file)
        self.token = token

    @staticmethod
    def _default_config():
        """Default configuration for Changelog CI"""
        return {
            "header_prefix": DEFAULT_VERSION_PREFIX,
            "commit_changelog": True,
            "comment_changelog": False,
            "pull_request_title_regex": DEFAULT_PULL_REQUEST_TITLE_REGEX,
            "version_regex": DEFAULT_SEMVER_REGEX,
            "group_config": DEFAULT_GROUP_CONFIG
        }

    @staticmethod
    def _get_changelog_line(item):
        """Generate each line of changelog"""
        return ("* [#{number}]({url}): {title}\n").format(
            number=item['number'],
            url=item['url'],
            title=item['title']
        )

    @staticmethod
    def _get_pull_request_title_and_number(event_path):
        """Gets pull request title from ``GITHUB_EVENT_PATH``"""
        with open(event_path, 'r') as json_file:
            # This is just a webhook payload available to the Action
            data = json.load(json_file)
            title = data["pull_request"]['title']
            number = data['number']

        return title, number

    def _parse_config(self, config_file):
        """parse the config file if not provided use default config"""
        if config_file:
            try:
                with open(config_file, 'r') as config_json:
                    config = json.load(config_json)
                # parse and validate user provided config file
                parse_config(config)
                return config
            except Exception as e:
                logger.error(
                    'Invalid Configuration file, error: %s\n', e
                )
        logger.warning(
            'Using Default Config to parse changelog'
        )
        # if config file not provided
        # or invalid fall back to default config
        return self._default_config()

    def _validate_pull_request(self):
        """Check if changelog should be generated for this pull request"""
        pattern = re.compile(self.config['pull_request_title_regex'])
        match = pattern.search(self.pull_request_title)

        if match:
            return True

        return

    def _get_version_number(self):
        import subprocess

        tag_lines = subprocess.check_output(['git', 'tag', '-l', '--sort=-creatordate', '--format=%(refname)']).decode("utf-8").splitlines()
        for tag in tag_lines:
            version = parse_version(tag.strip())
            if version:
                return version

        return None

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

    def _get_request_headers(self):
        """Get headers for GitHub API request"""
        headers = {
            'Accept': 'application/vnd.github.v3+json'
        }
        # if the user adds ``GITHUB_TOKEN`` add it to API Request
        # required for ``private`` repositories
        if self.token:
            headers.update({
                'authorization': 'Bearer {token}'.format(token=self.token)
            })

        return headers

    def _get_previous_release_date(self):
        import subprocess
        tag_times = subprocess.check_output(['git', 'tag', '-l', '--sort=-creatordate', '--format=%(creatordate)'])
        previous_tag_time = tag_times.decode("utf-8").splitlines()[1].strip()

        import datetime
        result = datetime.datetime.strptime(previous_tag_time, "%a %b %d %H:%M:%S %Y %z")

        return result

    def _get_pull_requests_after_last_release(self):
        """Get all the merged pull request after latest release"""
        items = []

        previous_release_date = self._get_previous_release_date()

        url = 'https://api.github.com/repos/{repo_name}/pulls?state=closed&base=master'.format(
            repo_name=self.repository
        )

        response = requests.get(url, headers=self._get_request_headers())
        from datetime import datetime

        if response.status_code == 200:
            response_data = response.json()
            for item in response_data:
                created_at = datetime.strptime(item['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                ninety_days = 3 * 30 * 24 * 3600
                if previous_release_date.timestamp() - created_at.timestamp() >= ninety_days:
                    break

                merged_at = item['merged_at']
                if not merged_at:
                    continue

                merged_at = datetime.strptime(merged_at, "%Y-%m-%dT%H:%M:%SZ")
                if merged_at.timestamp() <= previous_release_date.timestamp():
                    continue

                data = {
                    'title': item['title'],
                    'number': item['number'],
                    'url': item['html_url'],
                    'labels': [label['name'] for label in item['labels']]
                }
                items.append(data)
        else:
            logger.error(
                'GitHub API returned error response for %s, status code: %s',
                self.repository, response.status_code
            )

        return items

    def _parse_data(self, version, pull_request_data):
        """Parse the pull requests data and return a writable data structure"""
        string_data = (
            '# ' + self.config['header_prefix'] + ' ' + version + '\n\n'
        )

        group_config = self.config['group_config']

        if group_config:
            for config in group_config:

                if len(pull_request_data) == 0:
                    break

                items_string = ''

                for pull_request in pull_request_data:
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
                        pull_request_data.remove(pull_request)

                if items_string:
                    string_data += '\n#### ' + config['title'] + '\n\n'
                    string_data += '\n' + items_string

            if pull_request_data:
                # if they do not match any user provided group
                # Add items in ``Other Changes`` group
                string_data += '\n#### Other Changes\n\n'
                string_data += ''.join(map(self._get_changelog_line, pull_request_data))
        else:
            # If group config does not exist then append it without and groups
            string_data += ''.join(map(self._get_changelog_line, pull_request_data))

        return string_data

    def _write_changelog(self, string_data):
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

    def _comment_changelog(self, string_data):
        """Comments Changelog to the pull request"""
        if not self.token:
            # Token is required by the GitHub API to create a Comment
            # if not provided exit with error message
            logger.error(
                "Could not create a comment. "
                "``GITHUB_TOKEN`` is required for this operation.\n"
                "If you want to enable Changelog comment, please add "
                "``GITHUB_TOKEN`` to your workflow yaml file.\n"
                "Look at Changelog CI's documentation for more information."
            )
            return

        owner, repo = self.repository.split('/')

        payload = {
            'owner': owner,
            'repo': repo,
            'issue_number': self.pull_request_number,
            'body': string_data
        }

        url = (
            'https://api.github.com/repos/{repo}/issues/{number}/comments'
        ).format(
            repo=self.repository,
            number=self.pull_request_number
        )

        response = requests.post(
            url, headers=self._get_request_headers(),
            json=payload
        )

        if response.status_code != 201:
            # API should return 201, otherwise show error message
            logger.error(
                'Error while trying to create a comment.\n'
                'GitHub API returned error response for %s, status code: %s',
                self.repository, response.status_code
            )

    def run(self):
        """Entrypoint to the Changelog CI"""
        if (
            not self.config['commit_changelog'] and
            not self.config['comment_changelog']
        ):
            # if both commit_changelog and comment_changelog is set to false
            # then exit with warning and don't generate Changelog
            logger.warning(
                'Skipping Changelog generation as both ``commit_changelog`` '
                'and ``comment_changelog`` is set to False.\n'
                'If you did not intend to do this please set '
                'one or both of them to True.'
            )
            return

        version = self._get_version_number()

        if not version:
            # if the pull request title is not valid, exit the method
            # It might happen if the pull request is not meant to be release
            # or the title was not accurate.
            logger.warning(
                'Could not find matching version number. '
                'Regex tried: %s \n'
                'Aborting Changelog Generation',
                self.config['version_regex']
            )
            return

        pull_request_data = self._get_pull_requests_after_last_release()

        # exit the function if there is not pull request found
        if not pull_request_data:
            return

        string_data = self._parse_data(version, pull_request_data)

        if self.config['commit_changelog']:
            self._write_changelog(string_data)

        if self.config['comment_changelog']:
            self._comment_changelog(string_data)


def parse_config(config):
    """Parse and Validates user provided config, raises Error if not valid"""
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
        logger.warning(
            '``pull_request_title_regex`` was not provided or not valid '
            'Falling back to default regex.'
        )
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
        logger.warning(
            '``version_regex`` was not provided or not valid '
            'Falling back to default regex.'
        )
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
        logger.warning(
            '``commit_changelog`` was not provided or not valid '
            'Falling back to ``True``.'
        )
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
        logger.warning(
            '``comment_changelog`` was not provided or not valid '
            'Falling back to ``False``.'
        )
        # if comment_changelog is not provided default to False
        config.update({
            "comment_changelog": False
        })

    header_prefix = config.get('header_prefix')
    group_config = config.get('group_config')

    if not header_prefix or not isinstance(header_prefix, str):
        logger.warning(
            '``header_prefix`` was not provided or not valid '
            'Falling back to default regex.'
        )
        # if the header_prefix is not not available
        # fallback to default prefix
        config.update({
            "header_prefix": DEFAULT_VERSION_PREFIX
        })

    if not group_config or not isinstance(group_config, list):
        logger.warning(
            '``group_config`` was not provided or not valid '
            'Falling back to default group config.'
        )
        # if the group_config is not not available
        # fallback to default group_config
        config.update({
            "group_config": DEFAULT_GROUP_CONFIG
        })
    else:
        try:
            # Check if all the group configs match the schema
            for config in group_config:
                if not isinstance(config, dict):
                    raise TypeError(
                        'group_config items must have key, '
                        'value pairs of title and labels'
                    )
                title = config.get('title')
                labels = config.get('labels')

                if not title:
                    raise KeyError('group_config item must contain title')

                if not labels:
                    raise KeyError('group_config item must contain labels')

                if not isinstance(labels, list):
                    raise TypeError('group_config labels must be an Array')

        except Exception as e:
            logger.warning(
                'An error occurred while parsing ``group_config``. Error: %s\n'
                'Falling back to default group config.', e
            )
            # Fallback to default group_config
            config.update({
                "group_config": DEFAULT_GROUP_CONFIG
            })


def parse_version(tag):
    if tag.startswith("refs/tags/v"):
        return tag[11:]

    if tag.startswith("refs/tags/"):
        return tag[10:]

    return None



if __name__ == '__main__':
    # Default environment variable from GihHub
    # https://docs.github.com/en/actions/configuring-and-managing-workflows/using-environment-variables
    event_path = os.environ['GITHUB_EVENT_PATH']
    repository = os.environ['GITHUB_REPOSITORY']
    # User inputs from workflow
    filename = os.environ['INPUT_CHANGELOG_FILENAME']
    config_file = os.environ['INPUT_CONFIG_FILE']
    # Token provided from the workflow
    token = os.environ.get('GITHUB_TOKEN')

    # Initialize the Changelog CI
    ci = ChangelogCI(
        repository, event_path, filename=filename,
        config_file=config_file, token=token
    )
    ci.run()
