"""Resolve pull request and repository context."""

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, TypeAdapter, ValidationError

from ..errors import ChangelogError, ConfigurationError
from ..github import Payload
from ..models import Settings
from . import require_github_actions


class Repository(Payload):
    """Repository identity in a pull request event."""

    full_name: str
    default_branch: str | None = None


class Branch(Payload):
    """An event's base/head branch, including fork identity."""

    ref: str
    repo: Repository | None = None


class EventPR(Payload):
    """The pull request fields needed by the action."""

    title: str
    number: int | None = Field(default=None, gt=0)
    head: Branch
    base: Branch


class Event(Payload):
    """Supported event fields; other payload content is ignored."""

    number: int | None = Field(default=None, gt=0)
    pull_request: EventPR | None = None
    repository: Repository | None = None


@dataclass(frozen=True, slots=True)
class RunnerContext:
    """Repository and event facts supplied by the GitHub Actions runner."""

    repository: str
    is_pull_request: bool
    title: str = ""
    number: int | None = None
    head: str | None = None
    base: str | None = None
    head_repository: str | None = None


def load_context(settings: Settings) -> RunnerContext:
    """Read and validate the runner's event payload."""
    require_github_actions()
    import github_action_utils as gha

    if not (event_name := gha.vars.github.event_name):
        raise ConfigurationError("GitHub Actions requires GITHUB_EVENT_NAME.")
    if not (event_path := gha.vars.github.event_path):
        raise ConfigurationError("GitHub Actions requires GITHUB_EVENT_PATH.")
    try:
        event = TypeAdapter(Event).validate_json(
            Path(event_path).read_bytes(), strict=True
        )
    except (OSError, ValidationError) as exc:
        raise ConfigurationError("Could not read a valid event payload.") from exc
    pr = event.pull_request if event_name == "pull_request" else None
    repository = settings.repository or (
        event.repository.full_name if event.repository else ""
    )
    try:
        Settings(repository=repository)
        if pr and pr.head.repo:
            Settings(repository=pr.head.repo.full_name)
    except ValidationError as exc:
        raise ConfigurationError("Invalid repository in event payload.") from exc
    if not repository:
        raise ConfigurationError("Repository is missing from the runner context.")
    base: str | None
    if pr:
        head = gha.vars.github.head_ref or pr.head.ref
        base = gha.vars.github.base_ref or pr.base.ref
    else:
        head = None
        base = event.repository.default_branch if event.repository else None
        if (ref := gha.vars.github.ref or "").startswith("refs/heads/"):
            base = ref.removeprefix("refs/heads/")
    if event_name == "pull_request" and pr is None:
        raise ConfigurationError("Pull request data is missing from the runner event.")
    return RunnerContext(
        repository=repository,
        is_pull_request=event_name == "pull_request",
        title=pr.title if pr else "",
        number=(event.number or pr.number) if pr else None,
        head=head,
        base=base,
        head_repository=pr.head.repo.full_name if pr and pr.head.repo else None,
    )


def release_version(settings: Settings, event: RunnerContext) -> str | None:
    """Select a version from the PR title or release_version setting."""
    if not event.is_pull_request:
        if not settings.release_version:
            raise ChangelogError(
                "release_version is required for non-pull-request events."
            )
        return settings.release_version
    match = re.search(settings.version_regex, event.title)
    version = match.group() if match else settings.release_version
    if not version or (
        not re.search(settings.pull_request_title_regex, event.title)
        and not settings.release_version
    ):
        return None
    try:
        Settings(release_version=version)
    except ValidationError as exc:
        raise ConfigurationError("Release version must be single-line text.") from exc
    return version
