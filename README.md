![Changelog CI Banner](https://i.imgur.com/72lxPjs.png)

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/saadmk11/changelog-ci?style=flat-square)](https://github.com/saadmk11/changelog-ci/releases/latest)
![GitHub Workflow Status](https://img.shields.io/github/workflow/status/saadmk11/changelog-ci/Changelog%20CI?label=Changelog%20CI&style=flat-square)
[![GitHub](https://img.shields.io/github/license/saadmk11/changelog-ci?style=flat-square)](https://github.com/saadmk11/changelog-ci/blob/master/LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/changelog-ci)
[![GitHub stars](https://img.shields.io/github/stars/saadmk11/changelog-ci?color=success&style=flat-square)](https://github.com/saadmk11/changelog-ci/stargazers)

## What is Changelog CI?

Changelog CI is a GitHub Action that enables a project to utilize an
automatically generated changelog.

The workflow can be configured to perform **any (or all)** of the following actions

* **Generate** changelog using **Pull Request** or **Commit Messages**.

* **Prepend** the generated changelog to the `CHANGELOG.md` file and then **Commit** modified `CHANGELOG.md` file to the release pull request.

* Add a **Comment** on the release pull request with the generated changelog.

## How Does It Work:

Changelog CI uses `python` and `GitHub API` to generate changelog for a
repository. First, it tries to get the `latest release` from the repository (If
available). Then, it checks all the **pull requests** / **commits** merged after the last release
using the GitHub API. After that, it parses the data and generates
the `changelog`. Finally, It writes the generated changelog at the beginning of
the `CHANGELOG.md` (or user-provided filename) file. In addition to that, if a
user provides a config (JSON/YAML file), Changelog CI parses the user-provided config
file and renders the changelog according to users config. Then the changes
are **committed** and/or **commented** to the release Pull request.

## Usage:

To use this Action The pull **request title** must match with the
default `regex`
or the user-provided `regex` from the config file.

**Default Title Regex:** `^(?i:release)` (title must start with the word "
release" (case-insensitive))

**Default Changelog Type:** `pull_request` (Changelog will be generated using pull request title),
You can generate changelog using `commit_message` as well
[Using an optional configuration file](#using-an-optional-configuration-file).

**Default Version Number Regex:** This Regex will be checked against a Pull
Request title. This follows [`SemVer`](https://regex101.com/r/Ly7O1x/3/) (
Semantic Versioning) pattern. e.g. `1.0.0`, `1.0`, `v1.0.1` etc.

For more details on **Semantic Versioning pattern** go to this
link: https://regex101.com/r/Ly7O1x/3/

**Note:** You can use a custom regular expression to parse your changelog adding
one to the optional configuration file. To learn more, see
[Using an optional configuration file](#using-an-optional-configuration-file).

To **Enable Commenting, Disable Committing, Group Changelog Items, Use Commit Messages** and
some other options, see [Configuration](#configuration) to learn more.

To integrate `Changelog CI` with your repositories Actions, Put this step inside
your `.github/workflows/workflow.yml` file:

```yaml
- name: Run Changelog CI
    uses: saadmk11/changelog-ci@v0.8.0
    with:
      # Optional, you can provide any name for your changelog file,
      # We currently support Markdown (.md) and reStructuredText (.rst) files
      # defaults to `CHANGELOG.md` if not provided.
      changelog_filename: MY_CHANGELOG.md
      # Optional, only required when you want more customization
      # e.g: group your changelog by labels with custom titles,
      # different version prefix, pull request title and version number regex etc.
      # config file can be in JSON or YAML format.
      config_file: changelog-ci-config.json
      # Optional, This will be used to configure git
      # defaults to `github-actions[bot]` if not provided.
      committer_username: 'test'
      committer_email: 'test@test.com'
      # Optional
      github_token: ${{ secrets.GITHUB_TOKEN }}
```

**Changelog CI Badge:**

```markdown
![Changelog CI Status](https://github.com/<username>/<repository>/workflows/Changelog%20CI/badge.svg)
```

**Output:**

![Changelog CI Status](https://github.com/saadmk11/changelog-ci/workflows/Changelog%20CI/badge.svg)

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
      config_file: changelog-ci-config.yml
    ```

### Valid options

* `changelog_type`
  You can use `pull_request` (Default) or `commit_message` as the value for this option.
  `pull_request` option will generate changelog using pull request title.
  `commit_message` option will generate changelog using commit messages.

* `header_prefix`
  The prefix before the version number. e.g. `version:` in `Version: 1.0.2`

* `commit_changelog`
  Value can be `true` or `false`. if not provided defaults to `true`. If it is
  set to `true` then Changelog CI will commit to the release pull request.

* `comment_changelog`
  Value can be `true` or `false`. if not provided defaults to `false`. If it is
  set to `true` then Changelog CI will comment on the release pull request. This
  requires `GITHUB_TOKEN` to be added to the workflow.

* `pull_request_title_regex`
  If the pull request title matches with this `regex` Changelog CI will generate
  changelog for it. Otherwise, it will skip the changelog generation.
  If `pull_request_title_regex` is not provided defaults to `^(?i:release)`,
  then the title must begin with the word "release" (case-insensitive).

* `version_regex`
  This `regex` tries to find the version number from the pull request title. in
  case of no match, changelog generation will be skipped. if `version_regex` is
  not provided, it defaults to
  [`SemVer`](https://regex101.com/r/Ly7O1x/3/) pattern.

* `group_config`
  By adding this you can group changelog items by your repository labels with
  custom titles.

* `include_unlabeled_changes`
  if set to `false` the generated changelog will not contain the Pull Requests that are unlabeled or
  the labels are not on the `group_config` option. It defaults to `True`.

  **Note:** This option will only be used if the `group_config` option is added and
  the `changelog_type` option is `pull_request`.

* `unlabeled_group_title`
  This option will set the title of the unlabeled changes. It defaults to `Other Changes`.

  **Note:** This option will only be used if the `include_unlabeled_changes` option is set to `true`,
  `group_config` option is added and the `changelog_type` option is `pull_request`.

[See this example output with group_config](#example-changelog-output-using-config-file)

[See this example output without group_config](#example-changelog-output-without-using-config-file)

### Example Config File

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
[`SemVer`](https://regex101.com/r/Ly7O1x/3/) pattern. e.g. **`1.0.1`**
, **`v1.0.2`**.

* Here the changelog will be generated using commit messages because of `changelog_type: 'commit_message'`.

* Here **`pull_request_title_regex`** will match any pull request title that
starts with **`Release`**
you can match **Any Pull Request Title** by adding  this **`pull_request_title_regex": ".*"`**,

**[Click here to see the example output using this config](#example-changelog-output-using-config-file)**


## Example Workflow

```yaml
name: Changelog CI

# Controls when the action will run. Triggers the workflow on a pull request
on:
  pull_request:
    types: [ opened, reopened ]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      # Checks-out your repository
      - uses: actions/checkout@v2

      - name: Run Changelog CI
        uses: saadmk11/changelog-ci@v0.8.0
        with:
          # Optional
          changelog_filename: CHANGELOG.md
          # Optional
          config_file: changelog-ci-config.json
          # Optional
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

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
