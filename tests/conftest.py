import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from changelog_ci.github import GitHub
from tests.github import pull_request, response


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith(("GITHUB_", "CHANGELOG_CI_", "INPUT_", "_CHANGELOG_CI_")):
            monkeypatch.delenv(key)


@pytest.fixture
def runner_env() -> dict[str, str]:
    return {"GITHUB_ACTIONS": "true"}


@pytest.fixture
def github() -> Iterator[GitHub]:
    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(response)
    ) as client:
        yield client


@pytest.fixture
def cli_changes() -> list[dict[str, object]]:
    return [pull_request()]


@pytest.fixture
def cli_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cli_changes: list[dict[str, object]],
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response(request, changes=cli_changes)

    def factory(api_url: str, token: str | None = None) -> GitHub:
        return GitHub(api_url, token, transport=httpx.MockTransport(handle))

    monkeypatch.setattr("changelog_ci.cli.GitHub", factory)
    monkeypatch.chdir(tmp_path)
    return requests
