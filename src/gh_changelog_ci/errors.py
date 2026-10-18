"""Application errors and exit codes."""


class ChangelogError(Exception):
    """A failed changelog operation."""

    exit_code = 1


class ConfigurationError(ChangelogError):
    """Invalid options or missing context."""

    exit_code = 2


class APIError(ChangelogError):
    """A failed GitHub API request."""

    def __init__(self, operation: str, status: int | None = None) -> None:
        """Format the operation and HTTP status."""
        self.operation = operation
        self.status = status
        reason = {
            401: "authentication failed",
            403: "permission denied or rate limited",
            404: "repository or resource unavailable",
            429: "rate limited",
        }.get(status or 0, "request failed")
        super().__init__(
            f"GitHub {operation}: {reason}" + (f" (HTTP {status})" if status else "")
        )


class GitError(ChangelogError):
    """A failed Git command."""

    def __init__(self, operation: str, returncode: int) -> None:
        """Format the operation and Git exit status."""
        self.exit_code = returncode if 0 < returncode < 256 else 1
        super().__init__(
            f"Git {operation} failed (exit {returncode}); "
            "check checkout credentials and branch permissions."
        )
