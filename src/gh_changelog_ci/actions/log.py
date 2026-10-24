"""GitHub workflow messages, outputs and summaries."""

from collections.abc import Iterator
from contextlib import contextmanager

import github_action_utils as gha

from ..errors import ChangelogError
from . import require_github_actions


def _legacy_changelog(text: str) -> str:
    """Keep percent escaping in the composite action's changelog output."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


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
            with gha.group(title):
                yield

    def notice(self, message: str) -> None:
        """Write a workflow notice."""
        require_github_actions()
        if not self.quiet:
            gha.notice(message)

    def warning(self, message: str) -> None:
        """Write a workflow warning."""
        require_github_actions()
        gha.warning(message)

    def error(self, message: str) -> None:
        """Write a workflow error."""
        require_github_actions()
        gha.error(message)

    def content(self, text: str) -> None:
        """Suspend command interpretation while showing untrusted content."""
        require_github_actions()
        with gha.group("Changelog preview"), gha.stop_commands():
            gha.echo(text)

    def outputs(
        self, values: dict[str, str], *, summary: str = "", legacy: bool = False
    ) -> None:
        """Write outputs and an optional job summary."""
        require_github_actions()
        values = {
            key: _legacy_changelog(value) if legacy and key == "changelog" else value
            for key, value in values.items()
        }
        if (
            sum(len(value.encode("utf-16-le")) for value in values.values())
            > 1024 * 1024
        ):
            raise ChangelogError(
                "Changelog exceeds GitHub's 1 MB job output limit; "
                "the file has not been truncated."
            )
        if not gha.vars.github.output:
            raise ChangelogError("GitHub output requires GITHUB_OUTPUT.")
        for key, value in values.items():
            gha.set_output(key, value)
        if summary:
            summary = summary.removesuffix("\n")
            if len(summary.encode()) + 1 > 1024 * 1024:
                self.warning(
                    "Summary omitted: it exceeds GitHub's 1 MB step-summary limit."
                )
            elif gha.vars.github.step_summary:
                gha.append_job_summary(summary)
            else:
                raise ChangelogError("GitHub summary requires GITHUB_STEP_SUMMARY.")
