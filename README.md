![Changelog PR Banner](https://i.imgur.com/72lxPjs.png)

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/JonathanAquino/changelog-pr?style=flat-square)](https://github.com/JonathanAquino/changelog-pr/releases/latest)
![GitHub Workflow Status](https://img.shields.io/github/workflow/status/JonathanAquino/changelog-pr/Changelog%20CI?label=Changelog%20CI&style=flat-square)
[![GitHub](https://img.shields.io/github/license/JonathanAquino/changelog-pr?style=flat-square)](https://github.com/JonathanAquino/changelog-pr/blob/master/LICENSE)
[![GitHub Marketplace](https://img.shields.io/badge/Get%20It-on%20Marketplace-orange?style=flat-square)](https://github.com/marketplace/actions/changelog-pr)
[![GitHub stars](https://img.shields.io/github/stars/JonathanAquino/changelog-pr?color=success&style=flat-square)](https://github.com/JonathanAquino/changelog-pr/stargazers)

## What is Changelog PR?

Changelog PR is a GitHub Action that enables a project to utilize an
automatically generated changelog.

The workflow can be configured to perform **any (or all)** of the following actions

* **Generate** changelog using **Pull Request** or **Commit Messages**.

* **Prepend** the generated changelog to the `CHANGELOG.md` file and then **Commit** modified `CHANGELOG.md` file to the release pull request.

## How Does It Work:

Changelog PR uses `python` and `GitHub API` to generate changelog for a
repository. First, it tries to get the `latest release` from the repository (If
available). Then, it checks all the **pull requests** / **commits** merged after the last release
using the GitHub API. After that, it parses the data and generates
the `changelog`. Finally, It writes the generated changelog at the beginning of
the `CHANGELOG.md` (or user-provided filename) file. In addition to that, if a
user provides a config (JSON/YAML file), Changelog PR parses the user-provided config
file and renders the changelog according to users config. Then the changes
are **committed** to the release Pull request.

## Usage:

To use this Action The pull **request title** must match with the
default `regex`
or the user-provided `regex` from the config file.

**Default Title Regex:** `^(?i:release)` (title must start with the word "
release" (case-insensitive))

**Default Version Number Regex:** This Regex will be checked against a Pull
Request title. This follows [`SemVer`](https://regex101.com/r/Ly7O1x/3/) (
Semantic Versioning) pattern. e.g. `1.0.0`, `1.0`, `v1.0.1` etc.

For more details on **Semantic Versioning pattern** go to this
link: https://regex101.com/r/Ly7O1x/3/

**Note:** You can use a custom regular expression to parse your changelog adding
one to the optional configuration file. To learn more, see
[Using an optional configuration file](#using-an-optional-configuration-file).

To integrate `Changelog PR` with your repositories Actions, Put this step inside
your `.github/workflows/workflow.yml` file:

```yaml
- name: Run Changelog PR
    uses: JonathanAquino/changelog-pr@v0.8.0
    with:
      # Optional, you can provide any name for your changelog file,
      # defaults to `CHANGELOG.md` if not provided.
      changelog_filename: MY_CHANGELOG.md
      # Optional, only required when you want more customization
      # e.g: group your changelog by labels with custom titles,
      # different version prefix, pull request title and version number regex etc.
      # config file can be in JSON or YAML format.
      config_file: changelog-pr-config.json
      # Optional, This will be used to configure git
      # defaults to `github-actions[bot]` if not provided.
      committer_username: 'test'
      committer_email: 'test@test.com'
    env:
      # optional, only required for `private` repositories
      GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}
```

**Changelog PR Badge:**

```markdown
![Changelog PR Status](https://github.com/<username>/<repository>/workflows/Changelog%20CI/badge.svg)
```

**Output:**

![Changelog PR Status](https://github.com/JonathanAquino/changelog-pr/workflows/Changelog%20CI/badge.svg)

## Configuration

### Using an optional configuration file

Changelog PR is will run perfectly fine without including a configuration file.
If a user seeks to modify the default behaviors of Changelog PR, they can do so
by adding a `JSON` or `YAML` config file to the project. For example:

* Including `JSON` file `changelog-pr-config.json`:

    ```yaml
    with:
      config_file: changelog-pr-config.json
    ```

* Including `YAML` file `changelog-pr-config.yaml`:

    ```yaml
    with:
      config_file: changelog-pr-config.yml
    ```

### Valid options

* `group_config`
  By adding this you can group changelog items by your repository labels with
  custom titles.

[See this example output with group_config](#example-changelog-output-using-config-file)

[See this example output without group_config](#example-changelog-output-without-using-config-file)

### Example Config File

Written in JSON:

```json
{
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

**[Click here to see the example output using this config](#example-changelog-output-using-config-file)**


## Example Workflow

```yaml
name: Changelog PR

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

      - name: Run Changelog PR
        uses: JonathanAquino/changelog-pr@v0.8.0
        with:
          changelog_filename: CHANGELOG.md
          config_file: changelog-pr-config.json
        # Add this if you are using it on a private repository
        env:
          GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}
```

## Changelog PR in Action (Commit)
![Changelog PR](https://user-images.githubusercontent.com/24854406/93024522-1844d180-f619-11ea-9c25-57b4e95b822b.gif)


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
