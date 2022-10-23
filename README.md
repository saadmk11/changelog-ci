![Changelog CI Banner](https://i.imgur.com/72lxPjs.png)

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/saadmk11/changelog-ci?style=flat-square)](https://github.com/saadmk11/changelog-ci/releases/latest)
![GitHub Workflow Status](https://img.shields.io/github/workflow/status/saadmk11/changelog-ci/Changelog%20CI?label=Changelog%20CI&style=flat-square)
[![GitHub](https://img.shields.io/github/license/saadmk11/changelog-ci?style=flat-square)](https://github.com/saadmk11/changelog-ci/blob/master/LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/changelog-ci)
[![GitHub stars](https://img.shields.io/github/stars/saadmk11/changelog-ci?color=success&style=flat-square)](https://github.com/saadmk11/changelog-ci/stargazers)

## What is Changelog CI?

Changelog CI is a GitHub Action that enables a project to automatically generate changelogs.

Changelog CI can be triggered on `pull_request`, `workflow_dispatch` and any other events that can provide the required inputs.
Learn more about [events that trigger workflows](https://docs.github.com/en/actions/learn-github-actions/events-that-trigger-workflows)

The workflow can be configured to perform **any (or all)** of the following actions:

* For `pull_request` event:
  * **Generates** changelog using **Pull Request Titles** or **Commit Messages** made after the last release.
  * **Prepends** the generated changelog to the `CHANGELOG.md`/`CHANGELOG.rst` file.
  * Then **Commits** the modified `CHANGELOG.md`/`CHANGELOG.rst` file to the release pull request branch.
  * Adds a **Comment** on the release pull request with the generated changelog.


* For other events:
  * **Generate** changelog using **Pull Request Title** or **Commit Messages** made after the last release.
  * **Prepends** the generated changelog to the `CHANGELOG.md`/`CHANGELOG.rst` file.
  * Then Creates a **Pull Request** with the `CHANGELOG.md`/`CHANGELOG.rst` file changes.

## How Does It Work:

Changelog CI uses `python` and `GitHub API` to generate changelog for a
repository. First, it tries to get the `latest release` from the repository (If
available). Then, it checks all the **pull requests** / **commits** merged after the last release
using the GitHub API. After that, it parses the data and generates
the `changelog`. It is able to use `Markdown` or `reStructuredText` to generate Changelog.
Finally, It writes the generated changelog at the beginning of
the `CHANGELOG.md`/`CHANGELOG.rst` (or user-provided filename) file. In addition to that,
if a user provides a configuration file (JSON/YAML), Changelog CI parses the user-provided configuration
file and renders the changelog according to users configuration. Then, if the workflow run was triggered
by a `pull_request` event, the changes are **committed** and/or **commented** to the release Pull request,
otherwise a new **Pull Request** is created with the changes.

## Usage:

* To use this Action on a `pull_request` event, The pull **request title** must match with the
default `pull_request_title_regex` or the user-provided `pull_request_title_regex` from the config file.

* To use this Action on any other events, You must provide `release_version` as an input to the workflow.
It can be provided using `workflow_dispatch` events `input` option or from any other sources.

**Basic Integration (for `pull_request` event):** To integrate `Changelog CI` on your repositories, Put
`.github/workflows/changelog-ci.yml` file in your repository with the following content:

```yaml
name: Changelog CI

on:
  pull_request:
    types: [ opened ]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v2

      - name: Run Changelog CI
        uses: saadmk11/changelog-ci@v1.1.0
```

### Workflow input options

These are the inputs that can be provided on the workflow.

| Name | Required | Description | Default |
|------|----------|-------------|---------|
| `changelog_filename` | No | Name of the changelog file (Any file name with `.md` or `.rst` extension) | `CHANGELOG.md` |
| `config_file` | No | User configuration file path (configuration file can be in `JSON` or `YAML` format) | `null` |
| `committer_username` | No | Name of the user who will commit the changes to GitHub | github-actions[bot] |
| `committer_email` | No | Email Address of the user who will commit the changes to GitHub | github-actions[bot]@users.noreply.github.com |
| `release_version` | No (Required if workflow run is not triggered by a `pull_request` event) | The release version that will be used on the generated Changelog | `null` |
| `github_token` | No | `GITHUB_TOKEN` provided by the workflow run or Personal Access Token (PAT) | `github.token` |

#### Workflow with All Options:

```yaml
name: Changelog CI

on:
  pull_request:
    types: [ opened ]

  # Optionally you can use `workflow_dispatch` to run Changelog CI Manually
  workflow_dispatch:
    inputs:
      release_version:
        description: 'Set Release Version'
        required: true

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      # Checks-out your repository
      - uses: actions/checkout@v2

      - name: Run Changelog CI
        uses: saadmk11/changelog-ci@v1.1.0
        with:
          # Optional, you can provide any name for your changelog file,
          # We currently support Markdown (.md) and reStructuredText (.rst) files
          # defaults to `CHANGELOG.md` if not provided.
          changelog_filename: CHANGELOG.rst
          # Optional, only required when you want more customization
          # e.g: group your changelog by labels with custom titles,
          # different version prefix, pull request title and version number regex etc.
          # config file can be in JSON or YAML format.
          config_file: changelog-ci-config.json
          # Optional, This will be used to configure git
          # defaults to `github-actions[bot]` if not provided.
          committer_username: 'test'
          committer_email: 'test@test.com'
          # Optional, only required when you want to run Changelog CI 
          # on an event other than `pull_request` event.
          # In this example `release_version` is fetched from `workflow_dispatch` events input.
          # You can use any other method to fetch the release version
          # such as environment variable or from output of another action
          release_version: ${{ github.event.inputs.release_version }}
          # Optional
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

**Note:** To **Enable Commenting, Disable Committing, Group Changelog Items, Use Commit Messages** and
some other options, see [Configuration](#configuration) to learn more.

**Changelog CI Badge:**

```markdown
![Changelog CI Status](https://github.com/<username>/<repository>/workflows/Changelog%20CI/badge.svg)
```

![Changelog CI Status](https://github.com/saadmk11/changelog-ci/workflows/Changelog%20CI/badge.svg)

#### Workflow Output:

The workflow outputs the changelog as a `GitHub Action Output`. The name of the output is `changelog`.
The output can be used in other steps of the action. For example:

```yaml
- name: changelog-ci
  uses: saadmk11/changelog-ci@v1.1.0
  id: changelog-ci

- name: Get Changelog Output
  run: |
    echo "${{ steps.changelog-ci.outputs.changelog }}"
    echo "${{ steps.changelog-ci.outputs.changelog }}" >> $GITHUB_STEP_SUMMARY
```

Here the output is used to write the generated changelog to the GitHub Actions Job Summary.

## Configuration

### Using an optional configuration file

Changelog CI is will run perfectly fine without including a configuration file.
If a user seeks to modify the default behaviors of Changelog CI, they can do so
by adding a `JSON` or `YAML` config file to the project. For example:

* Including `JSON` file `changelog-ci-config.json`:

    ```yaml
    with:
      config_file: changelog-ci-config.json
    ```

* Including `YAML` file `changelog-ci-config.yaml`:

    ```yaml
    with:
      config_file: changelog-ci-config.yaml
    ```

### Configuration File options

These are the options that can be provided on the `config_file`.

| Name                        | Required | Description                                                                                                                                                                                                                                                                       | Default                                      | Options                            |
|-----------------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|------------------------------------|
| `changelog_type`            | No       | `pull_request` option will generate changelog using pull request title. `commit_message` option will generate changelog using commit messages.                                                                                                                                    | `pull_request`                               | `pull_request` or `commit_message` |
| `header_prefix`             | No       | The prefix before the version number. e.g. `version:` in `Version: 1.0.2`                                                                                                                                                                                                         | `Version:`                                   |                                    |
| `commit_changelog`          | No       | If it's set to `true` then Changelog CI will commit the changes to the release pull request. (A pull Request will be created with the changes if the workflow run is not triggered by a `pull_request` event)                                                                     | `true`                                       | `true` or `false`                  |
| `comment_changelog`         | No       | If it's set to `true` then Changelog CI will comment the generated changelog on the release pull request. (Only applicable for workflow runs triggered by a `pull_request` event)                                                                                                 | `false`                                      | `true` or `false`                  |
| `pull_request_title_regex`  | No       | If the pull request title matches with this `regex` Changelog CI will generate changelog for it. Otherwise, it will skip the changelog generation. (Only applicable for workflow runs triggered by a `pull_request` event)                                                        | `^(?i:release)`                              |                                    |
| `version_regex`             | No       | This `regex` is used to find the version name/number (e.g. `1.0.2`, `v2.0.2`) from the pull request title. in case of no match, changelog generation will be skipped. (Only applicable for workflow runs triggered by a `pull_request` event)                                     | [`SemVer`](https://regex101.com/r/Qayx0q/1/) |                                    |
| `group_config`              | No       | By adding this you can group changelog items by your repository labels with custom titles.                                                                                                                                                                                        | `null`                                       |                                    |
| `include_unlabeled_changes` | No       | if set to `false` the generated changelog will not contain the Pull Requests that are unlabeled or the labels are not on the `group_config` option. This option will only be used if the `group_config` option is added and the `changelog_type` option is set to `pull_request`. | `true`                                       | `true` or `false`                  |
| `unlabeled_group_title`     | No       | This option will set the title of the unlabeled changes. This option will only be used if the `include_unlabeled_changes` option is set to `true`, `group_config` option is added and the `changelog_type` option is set to `pull_request`.                                       | `Other Changes`                              |                                    |
| `exclude_labels`            | No       | If the pull Request includes one of the labels in this option the changelog for that pull request will be ignored.                                                                                                                                                                | `null`                                       |                                    |

#### Example Configuration File

Written in JSON:

```json
{
  "changelog_type": "commit_message",
  "header_prefix": "Version:",
  "commit_changelog": true,
  "comment_changelog": true,
  "include_unlabeled_changes": true,
  "unlabeled_group_title": "Unlabeled Changes",
  "pull_request_title_regex": "^Release",
  "version_regex": "v?([0-9]{1,2})+[.]+([0-9]{1,2})+[.]+([0-9]{1,2})\\s\\(\\d{1,2}-\\d{1,2}-\\d{4}\\)",
  "exclude_labels": ["bot", "dependabot", "ci"],
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

Written in YAML:

```yaml
changelog_type: 'commit_message' # or 'pull_request'
header_prefix: 'Version:'
commit_changelog: true
comment_changelog: true
include_unlabeled_changes: true
unlabeled_group_title: 'Unlabeled Changes'
pull_request_title_regex: '^Release'
version_regex: 'v?([0-9]{1,2})+[.]+([0-9]{1,2})+[.]+([0-9]{1,2})\s\(\d{1,2}-\d{1,2}-\d{4}\)'
exclude_labels:
  - bot
  - dependabot
  - ci
group_config:
  - title: Bug Fixes
    labels:
      - bug
      - bugfix
  - title: Code Improvements
    labels:
      - improvements
      - enhancement
  - title: New Features
    labels:
      - feature
  - title: Documentation Updates
    labels:
      - docs
      - documentation
      - doc
```

* In this Example **`version_regex`** matches any version number including date (
e.g: **`v1.1.0 (01-23-2018)`**) in the pull request title. If you don't provide
any `regex` Changelog CI will use default
[`SemVer`](https://regex101.com/r/Qayx0q/1/) pattern. e.g. **`1.0.1`**
, **`v1.0.2`**.

* Here the changelog will be generated using commit messages because of `changelog_type: 'commit_message'`.

* Here **`pull_request_title_regex`** will match any pull request title that starts with **`Release`**
you can match **Any Pull Request Title** by adding  this **`pull_request_title_regex": ".*"`**,

**[See this example output with group_config](#example-changelog-output-using-config-file-pull-request)**

**[See this example output without group_config](#example-changelog-output-without-using-config-file)**

## Changelog CI in Action (Comment & Commit)
![Changelog CI](https://user-images.githubusercontent.com/24854406/93024522-1844d180-f619-11ea-9c25-57b4e95b822b.gif)

# Example Changelog Output using config file (Pull Request):

## Version: v2.1.0 (02-25-2020)

#### Bug Fixes

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file

#### New Features

* [#68](https://github.com/test/test/pull/68): Update README.md

#### Documentation Updates

* [#66](https://github.com/test/test/pull/66): Docs update


## Version: v1.1.0 (01-01-2020)

#### Bug Fixes

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file

#### Documentation Updates

* [#66](https://github.com/test/test/pull/66): Docs update

# Example Changelog Output using config file (Commit Messages):

## Version: v2.1.0 (02-25-2020)

* [123456](https://github.com/test/test/commit/9bec2dbdsgfsdf8b4de11edb): Keep updating the readme
* [123456](https://github.com/test/test/commit/9bec2dbdsgfsdf8b4de11edb): Again updating the Same Readme file
* [123456](https://github.com/test/test/commit/9bec2dbdsgfsdf8b4de11edb): Update README.md
* [123456](https://github.com/test/test/commit/9bec2dbdsgfsdf8b4de11edb): Docs update


## Version: v1.1.0 (01-01-2020)

* [123456](https://github.com/test/test/commit/9bec2dbdsgfsdf8b4de11edb): Keep updating the readme
* [123456](https://github.com/test/test/commit/9bec2dbdsgfsdf8b4de11edb): Again updating the Same Readme file
* [123456](https://github.com/test/test/commit/9bec2dbdsgfsdf8b4de11edb): Docs update

# Example Changelog Output without using config file:

## Version: 0.0.2

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file
* [#55](https://github.com/test/test/pull/55): README update


## Version: 0.0.1

* [#43](https://github.com/test/test/pull/43): It feels like testing never ends
* [#35](https://github.com/test/test/pull/35): Testing again and again
* [#44](https://github.com/test/test/pull/44): This is again another test, getting tired
* [#37](https://github.com/test/test/pull/37): This is again another test


# License

The code in this project is released under the [MIT License](LICENSE).
