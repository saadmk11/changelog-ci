import httpx
import pytest
from pydantic import SecretStr

from gh_changelog_ci.actions.github import comment, create_pull_request
from gh_changelog_ci.errors import APIError, ChangelogError
from gh_changelog_ci.github import GitHub

pytestmark = pytest.mark.actions


@pytest.mark.parametrize("operation", ["comment", "pr"])
@pytest.mark.parametrize("status", [200, 202, 204])
def test_mutations_require_created_status_without_retrying(
    operation: str, status: int
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status)

    with (
        GitHub(
            "https://api.github.com", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(APIError) as error,
    ):
        if operation == "comment":
            comment(github, "o/r", 9, "body")
        else:
            create_pull_request(github, "o/r", "title", "notes", "main", "body")
    assert error.value.status == status
    assert error.value.operation == "write"
    assert len(requests) == 1
    assert requests[0].method == "POST"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"number": 0, "html_url": "https://github.com/o/r/pull/0"},
        {"number": 9, "html_url": 123},
    ],
)
def test_created_pr_requires_valid_response_fields(payload: dict[str, object]) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=payload)

    with (
        GitHub(
            "https://api.github.com",
            SecretStr("secret"),
            transport=httpx.MockTransport(handle),
        ) as github,
        pytest.raises(ChangelogError, match="invalid response") as error,
    ):
        create_pull_request(github, "o/r", "title", "notes", "main", "body")
    assert "secret" not in str(error.value)
    assert len(requests) == 1
