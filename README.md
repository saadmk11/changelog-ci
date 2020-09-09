![Changelog CI Banner](https://i.imgur.com/72lxPjs.png)


[![GitHub release (latest by date)](https://img.shields.io/github/v/release/saadmk11/changelog-ci?style=flat-square)](https://github.com/saadmk11/changelog-ci/releases/latest)
![GitHub Workflow Status](https://img.shields.io/github/workflow/status/saadmk11/changelog-ci/Changelog%20CI?label=Changelog%20CI&style=flat-square)
[![GitHub](https://img.shields.io/github/license/saadmk11/changelog-ci?style=flat-square)](https://github.com/saadmk11/changelog-ci/blob/master/LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/changelog-ci)
[![GitHub stars](https://img.shields.io/github/stars/saadmk11/changelog-ci?color=success&style=flat-square)](https://github.com/saadmk11/changelog-ci/stargazers)


## What is Changelog CI?

Changelog CI is a GitHub Action that generates changelog,
prepends it to ``CHANGELOG.md`` file and commits it to a release pull request


## How Does It Work:

Changelog CI uses ``python`` and ``GitHub API`` to generate changelog for a repository.
First, it tries to get the ``latest release`` from the repository (If available).
Then, it checks all the pull requests merged after the last release using the GitHub API.
After that it parses the data and generates the ``changelog``. Finally,
It writes the generated changelog at the beginning of the ``CHANGELOG.md`` (or user provided filename) file.
In addition to that, if an user provides a config (json file), Changelog CI parses the user provided config file
and renders the changelog according to users config.
Then the changes are **committed** and/or **commented** to the release Pull request.


## Usage:

To use this Action The pull **request title** must match with the default ``regex``
or the user provided ``regex`` from the config file.

**Default Title Regex:** ``^(?i:release)`` (title must start with the word "release" (case insensitive))

**Default Version Number Regex:** This follows [``SemVer``](https://regex101.com/r/Ly7O1x/3/) (Semantic Versioning) pattern.
e.g. ``1.0.0``, ``1.0``, ``v1.0.1`` etc.

For more details on **Semantic Versioning pattern** go to this link: https://regex101.com/r/Ly7O1x/3/

**Note:** [you can provide your own ``regex`` through the ``config`` file](#config-file-usage-optional)

To **Enable Commenting, Disable Committing, Group changed items** and many more options
Look at the [config file docs](#config-file-usage-optional).

To integrate ``Changelog CI`` with your repositories Actions,
Put this step inside your ``.github/workflows/workflow.yml`` file:

```yaml
- name: Run Changelog CI
    uses: saadmk11/changelog-ci@v0.5.6
    with:
      # Optional, you can provide any name for your changelog file,
      # defaults to ``CHANGELOG.md`` if not provided.
      changelog_filename: MY_CHANGELOG.md
      # Optional, only required when you want more customization
      # e.g: group your changelog by labels with custom titles,
      # different version prefix, pull request title and version number regex etc.
      config_file: changelog-ci-config.json
      # Optional, This will be used to configure git
      # defaults to ``github-actions[bot]`` if not provided.
      committer_username:  'test'
      committer_email:  'test@test.com'
    env:
      # optional, only required for ``private`` repositories
      # and required if the changelog comment 
      # option is turned on through the config file
      GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}
```

**Changelog CI Badge:**

```markdown
![Changelog CI Status](https://github.com/<username>/<repo_name>/workflows/Changelog%20CI/badge.svg)
``` 

**Output:**

![Changelog CI Status](https://github.com/saadmk11/changelog-ci/workflows/Changelog%20CI/badge.svg)


## Config File Usage (Optional):

Changelog CI config file is a ``JSON`` file that you can provide to you workflow like this:

```yaml
with:
  config_file: changelog-ci-config.json
```

The config file will give you more flexibility and customization options.

### Configuration Options:

* **header_prefix:** The prefix before the version number. e.g. ``version:`` in ``Version: 1.0.2``
* **commit_changelog:** Value can be ``true`` or ``false``. if not provided defaults to ``true``.
If it is set to ``true`` then Changelog CI will commit to the release pull request.
* **comment_changelog:** Value can be ``true`` or ``false``. if not provided defaults to ``false``.
If it is set to ``true`` then Changelog CI will comment on the release pull request.
This requires ``GITHUB_TOKEN`` to be added to the workflow.
* **pull_request_title_regex:** If the pull request title matches with this ``regex`` Changelog CI will generate changelog for it.
Otherwise it will skip changelog generation. If not provided defaults to ``^(?i:release)`` (title must start with the word "release" (case insensitive)).
* **version_regex:** This ``regex`` tries to find the version number from pull request title.
in case of no match changelog generation will be skipped.
if not provided defaults to [``SemVer``](https://regex101.com/r/Ly7O1x/3/) pattern.
* **group_config:** By adding this you can group changelog items by your repository labels with custom titles.
```
{
  // Custom title for groups
  "title": "Bug Fixes",
  // pull request labels that will match this group
  "labels": ["bug", "bugfix"]
}
```

[See this example with group_config](#example-changelog-output-using-config-file)

[See this example without group_config](#example-changelog-output-without-using-config-file)

#### Example Config File:

```json
{
  "header_prefix": "Version:",
  "commit_changelog": true,
  "comment_changelog": true,
  "pull_request_title_regex": "^Release",
  "version_regex": "v?([0-9]{1,2})+[.]+([0-9]{1,2})+[.]+([0-9]{1,2})\\s\\(\\d{1,2}-\\d{1,2}-\\d{4}\\)",
  "group_config": [
    {
      "title": "Bug Fixes",
      "labels": ["bug", "bugfix"]
    },
    {
      "title": "Code Improvements",
      "labels": ["improvements", "enhancement"]
    },
    {
      "title": "New Features",
      "labels": ["feature"]
    },
    {
      "title": "Documentation Updates",
      "labels": ["docs", "documentation", "doc"]
    }
  ]
}
```

In this Example **``version_regex``** matches any version number including date. e.g: **``v1.1.0 (01-23-2018)``**
If you don't provide any ``regex`` Changelog CI will use default 
[``SemVer``](https://regex101.com/r/Ly7O1x/3/) pattern. e.g. **``1.0.1``**, **``v1.0.2``**.

Here **``pull_request_title_regex``** will match any pull request that starts with **``Release``**
you can match **Any Pull Request Title** by adding this **``pull_request_title_regex": ".*"``**,

**[Click here to see the example output using this config](#example-changelog-output-using-config-file)**


## Example Workflow

```yaml
name: Changelog CI

# Controls when the action will run. Triggers the workflow on pull request
on:
  pull_request:
    types: [opened, reopened]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      # Checks-out your repository
      - uses: actions/checkout@v2

      - name: Run Changelog CI
        uses: saadmk11/changelog-ci@v0.5.6
        with:
          changelog_filename: CHANGELOG.md
          config_file: changelog-ci-config.json
        # Add this if you are using it on a private repository
        env:
          GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}
```


# Example Changelog Output using config file:

# Version: v2.1.0 (02-25-2020)

#### Bug Fixes

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file

#### New Features

* [#68](https://github.com/test/test/pull/68): Update README.md

#### Documentation Updates

* [#66](https://github.com/test/test/pull/66): Docs update


# Version: v1.1.0 (01-01-2020)

#### Bug Fixes

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file

#### Documentation Updates

* [#66](https://github.com/test/test/pull/66): Docs update


# Example Changelog Output without using config file:

# Version: 0.0.2

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file
* [#55](https://github.com/test/test/pull/55): README update


# Version: 0.0.1

* [#43](https://github.com/test/test/pull/43): It feels like testing never ends
* [#35](https://github.com/test/test/pull/35): Testing again and again
* [#44](https://github.com/test/test/pull/44): This is again another test, getting tired
* [#37](https://github.com/test/test/pull/37): This is again another test


# License

The code in this project is released under the [MIT License](LICENSE).
