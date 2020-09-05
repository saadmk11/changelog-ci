import json
import logging
import os

import requests


logger = logging.getLogger(__name__)


def validate_config(config):
    if not isinstance(config, dict):
        raise TypeError(
            'Configuration does not contain required key, value pairs'
        )

    header_prefix = config.get('header_prefix')
    sort_config = config.get('sort_config')

    if not header_prefix:
        raise KeyError('Configuration Must Contain header_prefix')

    if not isinstance(sort_config, list):
        raise TypeError('sort_config must be an Array')

    for config in sort_config:
        if not isinstance(config, dict):
            raise TypeError(
                'sort_config items must have key, '
                'value pairs of title and labels'
            )
        title = config.get('title')
        labels = config.get('labels')

        if not title:
            raise KeyError('sort_config item must contain title')

        if not labels:
            raise KeyError('sort_config item must contain labels')

        if not isinstance(labels, list):
            raise TypeError('sort_config labels must be an Array')


class ChangelogCI:

    def __init__(
        self, repository,
        event_path, filename='CHANGELOG.md',
        config_file='test.json', token=None
    ):
        self.repository = repository
        self.event_path = event_path
        self.filename = filename
        self.config = self._parse_config(config_file)
        self.token = token

    def _parse_config(self, config_file):
        if config_file:
            try:
                with open(config_file, 'r') as config_json:
                    config = json.load(config_json)
                validate_config(config)
                return config
            except Exception as e:
                logger.error(
                    'Invalid Configuration file, error: %s\n', e
                )
        logger.info(
            'Using Default Config to parse changelog'
        )
        return self._default_config()

    def _default_config(self):
        return {
            "header_prefix": "Version:",
            "sort_config": []
        }

    def _pull_request_title(self):
        title = ''
        with open(self.event_path, 'r') as json_file:
            data = json.load(json_file)
            title = data["pull_request"]['title']

        return title

    def _get_request_headers(self):
        headers = {
            'Accept': 'application/vnd.github.v3+json'
        }

        if self.token:
            headers.update({
                'authorization': 'Bearer {token}'.format(token=self.token)
            })

        return headers

    def _get_latest_release_date(self):
        url = (
            'https://api.github.com/repos/{repo_name}/releases/latest'
        ).format(repo_name=self.repository)

        published_date = ''

        response = requests.get(url, headers=self._get_request_headers())

        if response.status_code == 200:
            response_data = response.json()
            published_date = response_data['published_at']
        else:
            logger.warning(
                'Could not find any release for %s, status code: %s',
                self.repository, response.status_code
            )

        return published_date

    def _get_version_number(self):
        title = self._pull_request_title()
        version = ''
        try:
            if title.lower().startswith('release'):
                slices = title.split(' ')
                version = slices[1]
        except Exception:
            pass

        return version

    def _get_file_mode(self):
        if os.path.exists(self.filename):
            file_mode = 'r+'
        else:
            file_mode = 'w+'
        return file_mode

    def _get_pull_requests_after_last_release(self):
        items = []

        previous_release_date = self._get_latest_release_date()

        if previous_release_date:
            merged_date_filter = 'merged:>=' + previous_release_date
        else:
            # if there is no release for the repo then
            # do not filter by merged date
            merged_date_filter = ''

        url = (
            'https://api.github.com/search/issues'
            '?q=repo:{repo_name}+'
            'is:pr+'
            'is:merged+'
            'sort:author-date-asc+'
            '{merged_date_filter}'
            '&sort=merged'
        ).format(
            repo_name=self.repository,
            merged_date_filter=merged_date_filter
        )

        response = requests.get(url, headers=self._get_request_headers())

        if response.status_code == 200:
            response_data = response.json()

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
                logger.warning(
                    'There was no pull request made on %s after last release.',
                    self.repository
                )
        else:
            logger.error(
                'GitHub API returned error response for %s, status code: %s',
                self.repository, response.status_code
            )

        return items

    def write_changelog(self):
        version = self._get_version_number()

        if not version:
            logger.warning(
                'The title of the pull request is incorrect. '
                'Please use title like: '
                '``release <version_number> <other_text>``'
            )
            return

        pull_request_data = self._get_pull_requests_after_last_release()

        # exit the function if there is not pull request found
        if not pull_request_data:
            return

        file_mode = self._get_file_mode()
        filename = self.filename

        data_to_write = self._parse_data(pull_request_data)

        with open(filename, file_mode) as f:
            body = f.read()
            version = self.config['header_prefix'] + ' ' + version

            f.seek(0, 0)
            f.write(version + '\n')
            f.write('=' * len(version))
            f.write('\n\n')

            for data in data_to_write:
                title = data['title']
                if title:
                    f.write(title)

                f.writelines(data['items'])
                f.write('\n')

            if body:
                f.write('\n\n')
                f.write(body)

    def _parse_data(self, pull_request_data):
        data = []
        sort_config = self.config['sort_config']

        if sort_config:
            for config in sort_config:
                title = '#### ' + config['title'] + '\n\n'
                items = []

                for pull_request in pull_request_data:
                    if (
                            any(
                                label in pull_request['labels']
                                for label in config['labels']
                            )
                    ):
                        items.append(self._get_changelog_line(pull_request))
                        pull_request_data.remove(pull_request)

                data.append({'title': title, 'items': items})

            if pull_request_data:
                title = '#### Other Changes' + '\n\n'
                items = map(self._get_changelog_line, pull_request_data)

                data.append({'title': title, 'items': items})
        else:
            title = ''
            items = map(self._get_changelog_line, pull_request_data)

            data.append({'title': title, 'items': items})

        return data

    def _get_changelog_line(self, item):
        return ("* [#{number}]({url}): {title}\n").format(
            number=item['number'],
            url=item['url'],
            title=item['title']
        )


def validate_config(config):
    if not isinstance(config, dict):
        raise TypeError(
            'Configuration does not contain required key, value pairs'
        )

    header_prefix = config.get('header_prefix')
    sort_config = config.get('sort_config')

    if not header_prefix:
        raise KeyError('Configuration Must Contain header_prefix')

    if not isinstance(sort_config, list):
        raise TypeError('sort_config must be an Array')

    for config in sort_config:
        if not isinstance(config, dict):
            raise TypeError(
                'sort_config items must have key, '
                'value pairs of title and labels'
            )
        title = config.get('title')
        labels = config.get('labels')

        if not title:
            raise KeyError('sort_config item must contain title')

        if not labels:
            raise KeyError('sort_config item must contain labels')

        if not isinstance(labels, list):
            raise TypeError('sort_config labels must be an Array')


if __name__ == '__main__':
    event_path = os.environ['GITHUB_EVENT_PATH']
    repository = os.environ['GITHUB_REPOSITORY']
    filename = os.environ['INPUT_CHANGELOG_FILENAME']
    config_file = os.environ['INPUT_CHANGELOG_FILENAME']
    token = os.environ.get('GITHUB_TOKEN')

    ci = ChangelogCI(
        repository,
        event_path,
        filename=filename,
        config_file=config_file,
        token=token
    )
    ci.write_changelog()
