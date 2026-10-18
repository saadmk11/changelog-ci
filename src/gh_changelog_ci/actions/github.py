"""Create pull requests and comments through the GitHub API."""

from pydantic import Field, TypeAdapter

from ..errors import APIError
from ..github import GitHub, Payload, decode
from . import require_github_actions


class CreatedPR(Payload):
    """A newly created pull request."""

    number: int = Field(gt=0)
    html_url: str


def create_pull_request(
    github: GitHub, repository: str, title: str, branch: str, base: str, body: str
) -> CreatedPR:
    """Create a pull request without retrying the POST."""
    require_github_actions()
    response = github.request(
        "POST",
        f"repos/{repository}/pulls",
        payload={"title": title, "head": branch, "base": base, "body": body},
    )
    if response.status_code != 201:
        raise APIError("write", response.status_code)
    return decode(response, TypeAdapter(CreatedPR))


def comment(github: GitHub, repository: str, number: int, body: str) -> None:
    """Append a comment to a pull request."""
    require_github_actions()
    response = github.request(
        "POST", f"repos/{repository}/issues/{number}/comments", payload={"body": body}
    )
    if response.status_code != 201:
        raise APIError("write", response.status_code)
