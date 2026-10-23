"""GitHub workflow messages, outputs and summaries."""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import github_action_utils as gha
import typer

from ..errors import ChangelogError
from . import escape, require_github_actions


class GitHubReporter:
    """Report results to GitHub Actions."""

    def __init__(self, *, quiet: bool = False) -> None:
        """Configure workflow reporting."""
        require_github_actions()
        self.quiet = quiet

    @contextmanager
    def group(self, title: str) -> Iterator[None]:
        """Show collapsible workflow progress unless quiet."""
        require_github_actions()
        if self.quiet:
            yield
        else:
            gha.start_group(escape(title))
            try:
                yield
            finally:
                gha.end_group()

    def notice(self, message: str) -> None:
        """Write a workflow notice."""
        require_github_actions()
        if not self.quiet:
            gha.notice(escape(message))

    def warning(self, message: str) -> None:
        """Write a workflow warning."""
        require_github_actions()
        gha.warning(escape(message))

    def error(self, message: str) -> None:
        """Write a workflow error."""
        require_github_actions()
        gha.error(escape(message))

    def content(self, text: str) -> None:
        """Suspend command interpretation while showing untrusted content."""
        require_github_actions()
        delimiter = uuid.uuid4().hex
        with gha.group("Changelog preview"):
            typer.echo(f"::stop-commands::{delimiter}")
            typer.echo(text)
            typer.echo(f"::{delimiter}::")

    def outputs(
        self, values: dict[str, str], *, summary: str = "", legacy: bool = False
    ) -> None:
        """Write outputs and an optional job summary."""
        require_github_actions()
        if (
            sum(
                len(
                    (escape(value) if legacy and key == "changelog" else value).encode(
                        "utf-16-le"
                    )
                )
                for key, value in values.items()
            )
            > 1024 * 1024
        ):
            raise ChangelogError(
                "Changelog exceeds GitHub's 1 MB job output limit; "
                "the file has not been truncated."
            )
        output = os.environ.get("GITHUB_OUTPUT")
        if not output:
            raise ChangelogError("GitHub output requires GITHUB_OUTPUT.")
        for key, value in values.items():
            if legacy and key == "changelog":
                gha.set_output(key, value)
            else:
                delimiter = uuid.uuid4().hex
                with Path(output).open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
        if summary:
            if len(summary.encode()) > 1024 * 1024:
                self.warning(
                    "Summary omitted: it exceeds GitHub's 1 MB step-summary limit."
                )
            elif summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
                with Path(summary_path).open("a", encoding="utf-8") as stream:
                    stream.write(summary)
            else:
                raise ChangelogError("GitHub summary requires GITHUB_STEP_SUMMARY.")
