# Changelog CI


## What is Changelog CI?

Changelog CI is a GitHub Action that generates changelog, 
prepends it to CHANGELOG.md file and commits it to a release pull request


## How Does It Work:

It uses a python script with GitHub API to get the last release.
Then it checks all the pull request merged after the last release and
writes it to ``CHANGELOG.md`` or user provided file.
The pull request title must start with ``release <space> <version_number><space> *anything else``
for example: ``Release 0.1.1 releasing a new version``
The Changelog CI will see the pull request and submit a commit to the pull request
with the changes written in the ``CHANGELOG.md`` file.


## Usage:

To integrate ``Changelog CI`` with your repository Actions,
Put this step inside your ``.github/workflows/workflow.yml`` file:

```yaml
- name: Run Changelog CI
    uses: saadmk11/changelog-ci@0.4.0
    with:
      # You can provide any name for your changelog file,
      # defaults to ``CHANGELOG.md`` if not provided.
      changelog_filename: MY_CHANGELOG.md
      # optional, only required when you want to
      # group your changelog by labels and titles
      config_file: changelog-ci-config.json
    env:
      # This will be used to configure git
      # you can use secrets for it as well
      USERNAME:  'test'
      EMAIL:  'test@test.com'
      # optional, only required for ``private`` repositories
      GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}
```


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
        uses: saadmk11/changelog-ci@master
        with:
          changelog_filename: CHANGELOG.md
          config_file: changelog-ci-config.json
        env:
          USERNAME:  ${{secrets.USERNAME}}
          EMAIL:  ${{secrets.EMAIL}}
          GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}
```


### Group changelog by labels and titles

To group your changelog by labels and titles and have more control
over how your changelog looks you need to use Changelog CI's config file.
Its a ``json`` file you can add it to your workflow by adding this:

```yaml
with:
  config_file: changelog-ci-config.json
```

Example Config File:

```
{
  //  The prefix before the version number. "eg": ``Version: 0.0.2``
  "header_prefix": "Version:",
  "sort_config": [
    // You can add any number of sections to group by
    {
      // This will be the title of each section of the changelog
      "title": "Bug Fixes",
      // List of labels from your repository. You can add any number of labels
      // Pull Requests with these labels will be under the title above
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

This will look at the pull request ``labels`` and put them under the provided title.
By using the config file the output will be:

## Example Changelog Output using config file:


Version: 0.0.2
==============

#### Bug Fixes

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file :(

#### New Features

* [#68](https://github.com/test/test/pull/68): Update README.md

#### Documentation Updates

* [#66](https://github.com/test/test/pull/66): Docs update


Version: 0.0.1
==============

#### Bug Fixes

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file :(

#### Documentation Updates

* [#66](https://github.com/test/test/pull/66): Docs update


## Example Changelog Output without config file:

Version: 0.0.3
==============

* [#53](https://github.com/test/test/pull/57): Keep updating the readme
* [#54](https://github.com/test/test/pull/56): Again updating the Same Readme file :(
* [#55](https://github.com/test/test/pull/55): README update


Version: 0.0.2
==============

* [#53](https://github.com/test/test/pull/53): Testing again and again
* [#54](https://github.com/test/test/pull/54): This is again another test


Version: 0.0.1
==============

* [#43](https://github.com/test/test/pull/43): It feels like testing never ends :(
* [#35](https://github.com/test/test/pull/35): Testing again and again
* [#44](https://github.com/test/test/pull/44): This is again another test, getting tired
* [#37](https://github.com/test/test/pull/37): This is again another test


## License

The code in this project is released under the [MIT License](LICENSE).
