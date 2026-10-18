"""Settings, changelog entries and generation results."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


class Source(StrEnum):
    """Supported changelog sources."""

    PULL_REQUEST = "pull_request"
    COMMIT_MESSAGE = "commit_message"


class OutputMode(StrEnum):
    """Reporting destinations."""

    TERMINAL = "terminal"
    GITHUB = "github"


class Model(BaseModel):
    """Immutable application data with strict field validation."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
    )


class Group(Model):
    """An ordered label group."""

    title: str = Field(min_length=1)
    labels: tuple[str, ...] = Field(min_length=1)

    @field_validator("labels", mode="before")
    @classmethod
    def immutable_labels(cls, value: object) -> object:
        """Convert JSON label arrays to tuples."""
        return tuple(value) if isinstance(value, list) else value


class Settings(Model):
    """Configuration for the CLI and GitHub Action."""

    header_prefix: str = "Version:"
    commit_changelog: bool = True
    comment_changelog: bool = False
    pull_request_title_regex: str = r"^(?i:release)"
    version_regex: str = (
        r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.?(0|[1-9]\d*)?(?:-(("
        r"?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|["
        r"1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(["
        r"0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    )
    changelog_type: Source = Source.PULL_REQUEST
    group_config: tuple[Group, ...] = ()
    exclude_labels: tuple[str, ...] = ()
    include_unlabeled_changes: bool = True
    unlabeled_group_title: str = "Other Changes"
    changelog_filename: str = "CHANGELOG.md"
    committer_username: str = "github-actions[bot]"
    committer_email: str = "github-actions[bot]@users.noreply.github.com"
    release_version: str | None = None
    github_token: SecretStr | None = None

    repository: str = ""
    api_url: str = "https://api.github.com"
    workspace: Path = Field(default_factory=Path.cwd)
    create_pull_request: bool | None = None
    new_branch: str | None = None
    new_pull_request_title: str | None = None
    commit_message: str | None = None
    output_mode: OutputMode = OutputMode.TERMINAL
    stdout: bool = False
    dry_run: bool = False
    diff: bool = False
    verbose: bool = False
    quiet: bool = False
    summary: bool = False

    @field_validator("group_config", "exclude_labels", mode="before")
    @classmethod
    def immutable_collections(cls, value: object) -> object:
        """Convert configuration arrays to tuples."""
        return tuple(value) if isinstance(value, list) else value

    @field_validator("pull_request_title_regex", "version_regex")
    @classmethod
    def valid_regex(cls, value: str) -> str:
        """Validate regular expressions."""
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError("invalid regular expression") from exc
        return value

    @field_validator("changelog_filename")
    @classmethod
    def valid_filename(cls, value: str) -> str:
        """Require a Markdown or reStructuredText filename."""
        if not value.endswith((".md", ".rst")) or "\0" in value:
            raise ValueError("changelog filename must end in .md or .rst")
        return value

    @field_validator("release_version", "committer_username", "committer_email")
    @classmethod
    def single_line(cls, value: str | None) -> str | None:
        """Keep labels and Git identities nonempty and free of control characters."""
        if value is not None and (
            not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("expected nonempty single-line text")
        return value

    @property
    def rst(self) -> bool:
        """Whether the requested output uses reStructuredText."""
        return self.changelog_filename.endswith(".rst")

    @field_validator("repository")
    @classmethod
    def valid_repository(cls, value: str) -> str:
        """Validate an OWNER/REPO name."""
        if value and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise ValueError("expected OWNER/REPO")
        if any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("invalid repository")
        return value

    @field_validator("api_url")
    @classmethod
    def valid_api_url(cls, value: str) -> str:
        """Require a trusted HTTPS origin without embedded credentials."""
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("API URL must not contain control characters")
        url = urlsplit(value)
        _ = url.port
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "API URL must be HTTPS without credentials, query or fragment"
            )
        return value.rstrip("/")

    @field_validator("commit_message")
    @classmethod
    def valid_commit_message(cls, value: str | None) -> str | None:
        """Allow multiline messages but reject NUL before invoking Git."""
        if value is not None and "\0" in value:
            raise ValueError("commit message must not contain NUL")
        return value

    @model_validator(mode="after")
    def valid_output(self) -> "Settings":
        """Reject output combinations that would contaminate generated stdout."""
        if self.stdout and (
            self.summary or self.diff or self.output_mode == OutputMode.GITHUB
        ):
            raise ValueError("--stdout conflicts with summary, diff and GitHub output")
        if self.verbose and self.quiet:
            raise ValueError("--verbose conflicts with --quiet")
        if self.summary and self.output_mode != OutputMode.GITHUB:
            raise ValueError("--summary requires --output-mode github")
        return self


class Change(Model):
    """A source-independent rendered change."""

    identifier: str
    title: str
    url: str
    labels: tuple[str, ...] = ()


class GenerationRequest(Model):
    """The repository, version and cutoff used for generation."""

    settings: Settings
    repository: str
    version: str
    cutoff: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0)
    )
    legacy: bool = False


class GenerationResult(Model):
    """Collected entries and rendered release sections."""

    section: str = ""
    markdown: str = ""
    changes: tuple[Change, ...] = ()
