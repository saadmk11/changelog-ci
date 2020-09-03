import json
import logging
import os

import requests


logger = logging.getLogger(__name__)


class ChangelogCI:

    def __init__(self, repository, event_path, filename='CHANGELOG.md'):
        self.repository = repository
        self.event_path = event_path
        self.filename = filename

    def _pull_request_title(self):
        title = ''
        with open(self.event_path, 'r') as json_file:
            data = json.load(json_file)
            title = data["pull_request"]['title']

        return title

    def _get_latest_release_date(self):
        url = (
            'https://api.github.com/repos/{repo_name}/releases/latest'
        ).format(repo_name=self.repository)

        published_date = ''

        response = requests.get(url)

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
            '?q=repo:{repo_name}'
            '+is:pr+'
            'is:merged+'
            'sort:author-date-asc+'
            '{merged_date_filter}'
            '&sort=merged'
        ).format(
            repo_name=self.repository,
            merged_date_filter=merged_date_filter
        )

        response = requests.get(url)

        response_data = response.json()

        if response_data['total_count'] > 0:

            for item in response_data['items']:
                data = {
                    'title': item['title'],
                    'number': item['number'],
                    'url': item['html_url']
                }
                items.append(data)

        return items

    def write_changelog(self):
        version = self._get_version_number()

        if not version:
            print(
                'The title of the pull request is incorrect. ',
                'Please use title like: '
                '``release <version_number> <other_text>``'
            )
            return

        items = self._get_pull_requests_after_last_release()

        if not items:
            print('There was no pull request made after last release.')
            return

        file_mode = self._get_file_mode()
        filename = self.filename

        with open(filename, file_mode) as f:
            body = f.read()
            version = 'Version: ' + version

            f.seek(0, 0)

            f.write(version + '\n')
            f.write('=' * len(version))
            f.write('\n\n')

            for item in items:
                line = ("* [#{number}]({url}): {title}\n").format(
                    number=item['number'],
                    url=item['url'],
                    title=item['title']
                )
                f.write(line)

            if body:
                f.write('\n\n')
                f.write(body)


if __name__ == '__main__':
    event_path = os.environ['GITHUB_EVENT_PATH']
    repository = os.environ['GITHUB_REPOSITORY']
    filename = os.environ['INPUT_CHANGELOG_FILENAME']

    ci = ChangelogCI(repository, event_path, filename=filename)
    ci.write_changelog()
