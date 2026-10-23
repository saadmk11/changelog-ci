"""Command-line options and command dispatch."""

import importlib.util
import json
import os
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import resolve_actions, resolve_standalone
from .errors import APIError, ChangelogError, ConfigurationError
from .files import file_diff, output_path, prepend_content, write_atomic
from .generate import generate
from .github import GitHub
from .models import GenerationRequest, GroupBy, OutputMode, Settings, Source
from .reporting import Reporter, TerminalReporter

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    help="Generate changelogs from GitHub pull requests or commits.",
)


def version_callback(value: bool) -> None:
    """Print the installed package version."""
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show the installed version.",
        ),
    ] = False,
) -> None:
    """Generate a changelog or run the optional action integration."""


def require_actions() -> None:
    """Require the actions extra."""
    if importlib.util.find_spec("github_action_utils") is None:
        raise ConfigurationError(
            "Install the optional integration: pip install 'gh-changelog-ci[actions]'."
        )


def collect_options(ctx: typer.Context) -> dict[str, object]:
    """Collect explicit options and parse repeated JSON groups."""
    values = {key: value for key, value in ctx.params.items() if value is not None}
    for key in ("group_config", "exclude_labels"):
        if isinstance(values.get(key), tuple):
            if values[key]:
                values[key] = list(values[key])
            else:
                values.pop(key)
    for clear, name in (
        ("clear_groups", "group_config"),
        ("clear_exclude_labels", "exclude_labels"),
    ):
        if values.pop(clear, False):
            if values.get(name):
                raise ConfigurationError("Clear and add options cannot be combined.")
            values[name] = []
    if groups := values.get("group_config"):
        if not isinstance(groups, list):
            raise ConfigurationError("Groups must be JSON objects.")
        try:
            values["group_config"] = [json.loads(group) for group in groups]
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                "Each --group-config must be a JSON object."
            ) from exc
    return values


def generate_command(settings: Settings, github: GitHub, reporter: Reporter) -> None:
    """Generate, preview or write a changelog."""
    if not settings.repository or not settings.release_version:
        raise ConfigurationError("--repository and --release-version are required.")
    result = generate(
        GenerationRequest(
            settings=settings,
            repository=settings.repository,
            version=settings.release_version,
        ),
        github,
    )
    if settings.stdout:
        reporter.content(result.section)
        return
    path = output_path(settings.workspace, settings.changelog_filename)
    old, new = prepend_content(path, result.section)
    if settings.diff:
        reporter.content(file_diff(settings.changelog_filename, old, new))
    if settings.dry_run and not settings.diff:
        reporter.content(result.section)
    elif not settings.dry_run and old != new:
        write_atomic(path, new)
        reporter.notice("Changelog updated.")
    if not result.section:
        reporter.notice("No changes found.")
    else:
        reporter.outputs(
            {
                "changelog": result.section,
                "changed": str(old != new).lower(),
                "changelog-file": settings.changelog_filename,
                "pull-request-number": "",
                "pull-request-url": "",
            },
            summary=result.markdown if settings.summary else "",
        )


def execute(ctx: typer.Context, *, actions: bool) -> None:
    """Resolve settings and execute the selected command."""
    reporter: Reporter = TerminalReporter()
    try:
        if actions:
            from .actions import require_github_actions

            require_github_actions()
            require_actions()
        explicit = collect_options(ctx)
        if actions:
            settings = resolve_actions(explicit, os.environ, TerminalReporter())
        else:
            settings = resolve_standalone(explicit, os.environ)
        token = settings.github_token
        if token and os.environ.get("GITHUB_ACTIONS") == "true":
            from .actions import escape

            typer.echo(f"::add-mask::{escape(token.get_secret_value())}", err=True)
        reporter = TerminalReporter(quiet=settings.quiet)
        if settings.output_mode == OutputMode.GITHUB:
            from .actions import require_github_actions

            require_github_actions()
            require_actions()
            if not os.environ.get("GITHUB_OUTPUT"):
                raise ConfigurationError("GitHub output requires GITHUB_OUTPUT.")
            if settings.summary and not os.environ.get("GITHUB_STEP_SUMMARY"):
                raise ConfigurationError("GitHub summary requires GITHUB_STEP_SUMMARY.")
            from .actions.reporting import GitHubReporter

            reporter = GitHubReporter(quiet=settings.quiet)
        if settings.verbose:
            reporter.notice(f"Collecting {settings.changelog_type.value} changes.")
        with GitHub(settings.api_url, token) as github:
            if actions:
                from .actions.runner import run

                run(
                    settings,
                    github,
                    reporter,
                    legacy=os.environ.get("_CHANGELOG_CI_COMPOSITE") == "true",
                )
            else:
                generate_command(settings, github, reporter)
    except ChangelogError as exc:
        reporter.error(str(exc))
        # Composite collection failures use the documented success/skip status.
        if (
            actions
            and os.environ.get("_CHANGELOG_CI_COMPOSITE") == "true"
            and isinstance(exc, APIError)
            and exc.operation == "collection"
            and exc.status is not None
            and exc.status not in {401, 403, 429}
        ):
            raise typer.Exit(0) from None
        raise typer.Exit(exc.exit_code) from None
    except (OSError, UnicodeError):
        reporter.error(
            "Filesystem operation failed; check workspace paths and permissions."
        )
        raise typer.Exit(1) from None


RepositoryOption = Annotated[
    str | None,
    typer.Option(
        "--repository", help="GitHub OWNER/REPO.", rich_help_panel="Repository"
    ),
]

ApiUrlOption = Annotated[
    str | None,
    typer.Option(
        "--api-url", help="Trusted GitHub API URL.", rich_help_panel="Repository"
    ),
]

WorkspaceOption = Annotated[
    Path | None,
    typer.Option("--workspace", help="Workspace root.", rich_help_panel="Repository"),
]

ConfigFileOption = Annotated[
    Path | None,
    typer.Option(
        "--config-file",
        help="JSON or YAML configuration file.",
        rich_help_panel="Configuration",
    ),
]

ChangelogFilenameOption = Annotated[
    str | None,
    typer.Option(
        "--changelog-filename",
        help="Output .md or .rst filename.",
        rich_help_panel="Configuration",
    ),
]

CommitterUsernameOption = Annotated[
    str | None,
    typer.Option(
        "--committer-username",
        help="Git committer name.",
        rich_help_panel="Configuration",
    ),
]

CommitterEmailOption = Annotated[
    str | None,
    typer.Option(
        "--committer-email",
        help="Git committer email.",
        rich_help_panel="Configuration",
    ),
]

ReleaseVersionOption = Annotated[
    str | None,
    typer.Option(
        "--release-version",
        help="Release label to render.",
        rich_help_panel="Configuration",
    ),
]

GithubTokenOption = Annotated[
    str | None,
    typer.Option(
        "--github-token",
        help="GitHub token; prefer environment transport.",
        rich_help_panel="Repository",
    ),
]

ChangelogTypeOption = Annotated[
    Source | None,
    typer.Option(
        "--changelog-type",
        help="Collect pull requests or commit messages.",
        rich_help_panel="Configuration",
    ),
]

HeaderPrefixOption = Annotated[
    str | None,
    typer.Option(
        "--header-prefix",
        help="Text before the release label.",
        rich_help_panel="Configuration",
    ),
]

PullRequestTitleRegexOption = Annotated[
    str | None,
    typer.Option(
        "--pull-request-title-regex",
        help="Release PR title pattern (actions only).",
        rich_help_panel="Configuration",
    ),
]

VersionRegexOption = Annotated[
    str | None,
    typer.Option(
        "--version-regex",
        help="Release version pattern (actions only).",
        rich_help_panel="Configuration",
    ),
]

GroupByOption = Annotated[
    GroupBy | None,
    typer.Option(
        "--group-by",
        help="Group pull requests by labels or linked issue type.",
        rich_help_panel="Configuration",
    ),
]

GroupConfigOption = Annotated[
    list[str] | None,
    typer.Option(
        "--group-config",
        help="Repeat JSON objects with title and labels or issue_types.",
        rich_help_panel="Configuration",
    ),
]

ExcludeLabelsOption = Annotated[
    list[str] | None,
    typer.Option(
        "--exclude-label",
        help="Repeat labels to exclude.",
        rich_help_panel="Configuration",
    ),
]

ClearGroupsOption = Annotated[
    bool | None,
    typer.Option(
        "--clear-groups",
        help="Clear configured groups.",
        rich_help_panel="Configuration",
    ),
]

ClearExcludeLabelsOption = Annotated[
    bool | None,
    typer.Option(
        "--clear-exclude-labels",
        help="Clear configured exclusions.",
        rich_help_panel="Configuration",
    ),
]

IncludeUnlabeledChangesOption = Annotated[
    bool | None,
    typer.Option(
        "--include-unlabeled-changes/--no-include-unlabeled-changes",
        help="Include changes unmatched by groups.",
        rich_help_panel="Configuration",
    ),
]

UnlabeledGroupTitleOption = Annotated[
    str | None,
    typer.Option(
        "--unlabeled-group-title",
        help="Heading for unmatched changes.",
        rich_help_panel="Configuration",
    ),
]

OutputModeOption = Annotated[
    OutputMode | None,
    typer.Option(
        "--output-mode",
        help="Terminal or GitHub reporting.",
        rich_help_panel="Output",
    ),
]

StdoutOption = Annotated[
    bool | None,
    typer.Option(
        "--stdout",
        help="Print only the generated section.",
        rich_help_panel="Output",
    ),
]

DryRunOption = Annotated[
    bool | None,
    typer.Option(
        "--dry-run", help="Preview without mutations.", rich_help_panel="Output"
    ),
]

DiffOption = Annotated[
    bool | None,
    typer.Option("--diff", help="Show a unified file diff.", rich_help_panel="Output"),
]

VerboseOption = Annotated[
    bool | None,
    typer.Option(
        "--verbose", help="Show additional progress details.", rich_help_panel="Output"
    ),
]

QuietOption = Annotated[
    bool | None,
    typer.Option(
        "--quiet",
        help="Suppress progress and automatic previews.",
        rich_help_panel="Output",
    ),
]

SummaryOption = Annotated[
    bool | None,
    typer.Option(
        "--summary/--no-summary",
        help="Append an opt-in GitHub job summary.",
        rich_help_panel="Output",
    ),
]

CommitChangelogOption = Annotated[
    bool | None,
    typer.Option(
        "--commit-changelog/--no-commit-changelog",
        help="Commit and push the changelog.",
        rich_help_panel="Operations",
    ),
]

CommentChangelogOption = Annotated[
    bool | None,
    typer.Option(
        "--comment-changelog/--no-comment-changelog",
        help="Append a release PR comment.",
        rich_help_panel="Operations",
    ),
]

CreatePullRequestOption = Annotated[
    bool | None,
    typer.Option(
        "--create-pull-request/--no-create-pull-request",
        help="Open a PR after committing a new branch.",
        rich_help_panel="Operations",
    ),
]

NewBranchOption = Annotated[
    str | None,
    typer.Option(
        "--new-branch",
        help="Override the timestamp branch name.",
        rich_help_panel="Operations",
    ),
]

NewPullRequestTitleOption = Annotated[
    str | None,
    typer.Option(
        "--new-pull-request-title",
        help="Override the created PR title.",
        rich_help_panel="Operations",
    ),
]

CommitMessageOption = Annotated[
    str | None,
    typer.Option(
        "--commit-message",
        help="Override the generated commit message.",
        rich_help_panel="Operations",
    ),
]


@app.command("generate")
def generate_cli(
    ctx: typer.Context,
    repository: RepositoryOption = None,
    api_url: ApiUrlOption = None,
    workspace: WorkspaceOption = None,
    config_file: ConfigFileOption = None,
    changelog_filename: ChangelogFilenameOption = None,
    release_version: ReleaseVersionOption = None,
    github_token: GithubTokenOption = None,
    changelog_type: ChangelogTypeOption = None,
    header_prefix: HeaderPrefixOption = None,
    group_by: GroupByOption = None,
    group_config: GroupConfigOption = None,
    exclude_labels: ExcludeLabelsOption = None,
    clear_groups: ClearGroupsOption = None,
    clear_exclude_labels: ClearExcludeLabelsOption = None,
    include_unlabeled_changes: IncludeUnlabeledChangesOption = None,
    unlabeled_group_title: UnlabeledGroupTitleOption = None,
    output_mode: OutputModeOption = None,
    stdout: StdoutOption = None,
    dry_run: DryRunOption = None,
    diff: DiffOption = None,
    verbose: VerboseOption = None,
    quiet: QuietOption = None,
    summary: SummaryOption = None,
) -> None:
    """Generate a changelog without committing, pushing or commenting."""
    execute(ctx, actions=False)


@app.command("actions")
def actions_cli(
    ctx: typer.Context,
    config_file: ConfigFileOption = None,
    changelog_filename: ChangelogFilenameOption = None,
    committer_username: CommitterUsernameOption = None,
    committer_email: CommitterEmailOption = None,
    release_version: ReleaseVersionOption = None,
    github_token: GithubTokenOption = None,
    changelog_type: ChangelogTypeOption = None,
    header_prefix: HeaderPrefixOption = None,
    pull_request_title_regex: PullRequestTitleRegexOption = None,
    version_regex: VersionRegexOption = None,
    group_by: GroupByOption = None,
    group_config: GroupConfigOption = None,
    exclude_labels: ExcludeLabelsOption = None,
    clear_groups: ClearGroupsOption = None,
    clear_exclude_labels: ClearExcludeLabelsOption = None,
    include_unlabeled_changes: IncludeUnlabeledChangesOption = None,
    unlabeled_group_title: UnlabeledGroupTitleOption = None,
    output_mode: OutputModeOption = None,
    dry_run: DryRunOption = None,
    diff: DiffOption = None,
    verbose: VerboseOption = None,
    quiet: QuietOption = None,
    summary: SummaryOption = None,
    commit_changelog: CommitChangelogOption = None,
    comment_changelog: CommentChangelogOption = None,
    create_pull_request: CreatePullRequestOption = None,
    new_branch: NewBranchOption = None,
    new_pull_request_title: NewPullRequestTitleOption = None,
    commit_message: CommitMessageOption = None,
) -> None:
    """Run workflow operations inside GitHub Actions with the actions extra."""
    execute(ctx, actions=True)
