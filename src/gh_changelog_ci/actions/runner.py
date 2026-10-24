"""Generate changelogs and run Git and GitHub updates."""

import time
from contextlib import nullcontext
from urllib.parse import urlsplit

from ..errors import APIError, ChangelogError, ConfigurationError
from ..files import file_diff, output_path, prepend_content, write_atomic
from ..generate import generate
from ..github import GitHub
from ..log import Reporter
from ..models import GenerationRequest, OutputMode, Settings
from . import require_github_actions
from .context import load_context, release_version
from .git import Git, branch_component
from .github import comment, create_pull_request


def run(
    settings: Settings,
    github: GitHub,
    reporter: Reporter,
    *,
    legacy: bool = False,
) -> None:
    """Generate the changelog and apply the requested operations."""
    require_github_actions()
    event = load_context(settings)
    if settings.create_pull_request and not settings.commit_changelog:
        raise ConfigurationError("Creating a pull request requires committing.")
    version = release_version(settings, event)
    if version is None:
        reporter.notice("Skipping: pull request title/version did not match.")
        return
    if not settings.commit_changelog and not settings.comment_changelog:
        raise ChangelogError(
            "Skipping: commit_changelog and comment_changelog are both false."
        )
    create_pr = (
        settings.create_pull_request
        if settings.create_pull_request is not None
        else not event.is_pull_request and settings.commit_changelog
    )
    if create_pr and event.is_pull_request:
        raise ConfigurationError("PR creation requires a non-pull-request event.")
    if create_pr and not settings.github_token and not legacy and not settings.dry_run:
        raise ConfigurationError("A GitHub token is required to create a pull request.")
    if event.is_pull_request and (
        settings.new_branch or settings.new_pull_request_title
    ):
        raise ConfigurationError("New-PR overrides require a non-pull-request event.")
    if settings.comment_changelog and event.is_pull_request:
        if not event.number:
            raise ConfigurationError("A pull request number is required to comment.")
        if not settings.github_token and not legacy and not settings.dry_run:
            raise ConfigurationError("A GitHub token is required to comment.")
    title = f"[Changelog CI] Add Changelog for Version {version}"
    branch = (
        event.head
        if event.is_pull_request
        else settings.new_branch
        or f"changelog-ci-{branch_component(version)}-{int(time.time())}"
    )
    git: Git | None = None
    if settings.commit_changelog:
        if event.is_pull_request and not event.head_repository:
            raise ConfigurationError(
                "Pull request head repository is missing from the runner event."
            )
        git = Git(settings.workspace, settings)
        git.validate(
            event.head_repository or event.repository,
            hostname="github.com"
            if urlsplit(settings.api_url).hostname == "api.github.com"
            else urlsplit(settings.api_url).hostname or "",
        )
        base = event.head if event.is_pull_request else event.base
        if not base and not event.is_pull_request:
            remote_head = git.run(
                "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False
            ).stdout.strip()
            base = remote_head.removeprefix("refs/remotes/origin/") or None
        if not base or not branch:
            raise ConfigurationError(
                "A real base/head branch is required for committing."
            )
        git.branch(base)
        git.branch(branch)
        if not settings.dry_run and event.is_pull_request:
            with (
                reporter.group("Prepare changelog branch")
                if settings.verbose
                else nullcontext()
            ):
                if settings.verbose:
                    reporter.notice(f"Checking out pull request branch {branch}.")
                git.prepare(base, branch, new=False)
    else:
        base = event.base
    with reporter.group("Generate changelog"):
        reporter.notice(f"Generating changelog for version {version}.")
        if settings.verbose:
            reporter.notice(f"Repository: {event.repository}.")
        result = generate(
            GenerationRequest(
                settings=settings,
                repository=event.repository,
                version=version,
                legacy=True,
            ),
            github,
        )
        if settings.verbose:
            count = len(result.changes)
            reporter.notice(f"Collected {count} change{'s' if count != 1 else ''}.")
    if not result.section:
        reporter.notice("No changes found.")
        return
    if git and base and branch and not settings.dry_run and not event.is_pull_request:
        with (
            reporter.group("Prepare changelog branch")
            if settings.verbose
            else nullcontext()
        ):
            if settings.verbose:
                reporter.notice(f"Creating branch {branch} from {base}.")
            git.prepare(base, branch, new=True)
    path = output_path(
        settings.workspace,
        settings.changelog_filename,
        require_parent=False,
    )
    old, new = prepend_content(path, result.section)
    changed = old != new
    values = {
        "changelog": result.section,
        "changed": str(changed).lower(),
        "changelog-file": settings.changelog_filename,
        "pull-request-number": "",
        "pull-request-url": "",
    }
    if settings.diff:
        reporter.content(file_diff(settings.changelog_filename, old, new))
    elif (
        settings.output_mode == OutputMode.GITHUB
        and settings.verbose
        and not settings.dry_run
    ):
        reporter.content(result.section)
    if settings.dry_run:
        if not settings.diff:
            reporter.content(result.section)
        operations = tuple(
            description
            for enabled, description in (
                (settings.commit_changelog, "write, commit and push the changelog"),
                (create_pr, "open a pull request"),
                (
                    settings.comment_changelog and event.is_pull_request,
                    "append a PR comment",
                ),
            )
            if enabled
        )
        reporter.notice(
            "Dry run: would " + "; ".join(operations) + "."
            if operations
            else "Dry run: no supported mutations for this event."
        )
    else:
        if git and branch:
            committed = False
            with reporter.group("Commit and push changelog"):
                if settings.verbose:
                    reporter.notice(
                        f"Commit author: {settings.committer_username} "
                        f"<{settings.committer_email}>."
                    )
                    reporter.notice(f"Changelog file: {settings.changelog_filename}.")
                    reporter.notice(f"Push branch: {branch}.")
                if changed:
                    if settings.verbose:
                        reporter.notice(f"Updating {settings.changelog_filename}.")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    write_atomic(path, new)
                    committed = git.commit(branch, settings.commit_message or title)
                if committed:
                    reporter.notice("Changelog committed and pushed.")
                else:
                    reporter.notice("Changelog is already up to date; nothing to push.")
            if committed and create_pr and base:
                with reporter.group("Create pull request"):
                    if settings.verbose:
                        reporter.notice(
                            f"Opening a pull request from {branch} to {base}."
                        )
                    try:
                        created = create_pull_request(
                            github,
                            event.repository,
                            settings.new_pull_request_title or title,
                            branch,
                            base,
                            result.markdown,
                        )
                        values.update(
                            {
                                "pull-request-number": str(created.number),
                                "pull-request-url": created.html_url,
                            }
                        )
                        reporter.notice(f"Pull request opened at {created.html_url}.")
                    except APIError as exc:
                        if not legacy or exc.status is None or exc.status in {401, 403}:
                            raise
                        reporter.warning(str(exc))
        if settings.comment_changelog:
            if not event.is_pull_request:
                reporter.warning("Comments are only supported for pull_request events.")
            elif not settings.github_token:
                reporter.warning("A GitHub token is required to comment.")
            elif event.number:
                with reporter.group("Comment changelog"):
                    if settings.verbose:
                        reporter.notice(
                            f"Adding changelog to pull request #{event.number}."
                        )
                    try:
                        comment(github, event.repository, event.number, result.markdown)
                        reporter.notice(
                            f"Changelog comment added to pull request #{event.number}."
                        )
                    except APIError as exc:
                        if not legacy or exc.status is None or exc.status in {401, 403}:
                            raise
                        reporter.warning(str(exc))
    reporter.outputs(
        values, summary=result.markdown if settings.summary else "", legacy=legacy
    )
    if not settings.dry_run:
        reporter.notice("Changelog CI complete.")
