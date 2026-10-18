"""Terminal and workflow reporting."""

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

import typer


class Reporter(Protocol):
    """Progress messages, content and command results."""

    def group(self, title: str) -> AbstractContextManager[None]:
        """Group related progress messages and operations."""
        ...

    def notice(self, message: str) -> None:
        """Report progress."""
        ...

    def warning(self, message: str) -> None:
        """Report a recoverable failure."""
        ...

    def error(self, message: str) -> None:
        """Report an operation that failed."""
        ...

    def content(self, text: str) -> None:
        """Show untrusted generated content safely."""
        ...

    def outputs(
        self, values: dict[str, str], *, summary: str = "", legacy: bool = False
    ) -> None:
        """Publish workflow results when applicable."""
        ...


class TerminalReporter:
    """Write diagnostics to stderr and changelogs to stdout."""

    def __init__(self, *, quiet: bool = False) -> None:
        """Configure progress messages."""
        self.quiet = quiet

    def group(self, title: str) -> AbstractContextManager[None]:
        """Keep terminal diagnostics free of workflow group commands."""
        return nullcontext()

    def notice(self, message: str) -> None:
        """Report progress unless quiet."""
        if not self.quiet:
            typer.echo(message, err=True)

    def warning(self, message: str) -> None:
        """Write a warning to stderr."""
        typer.echo(f"Warning: {message}", err=True)

    def error(self, message: str) -> None:
        """Write an error to stderr."""
        typer.echo(f"Error: {message}", err=True)

    def content(self, text: str) -> None:
        """Write the changelog section to stdout."""
        typer.echo(text, nl=False)

    def outputs(
        self, values: dict[str, str], *, summary: str = "", legacy: bool = False
    ) -> None:
        """Ignore workflow outputs in terminal mode."""
