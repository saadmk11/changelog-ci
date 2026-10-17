from datetime import UTC, datetime

import httpx
import pytest

from changelog_ci.errors import APIError, ChangelogError
from changelog_ci.github import GitHub
from tests.github import pull_request

CUTOFF = datetime(2026, 1, 2, tzinfo=UTC)
SINCE = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_release_failures_are_not_no_release(status: int) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="token-secret")

    with (
        GitHub(
            "https://api.github.com",
            "token-secret",
            transport=httpx.MockTransport(handle),
        ) as github,
        pytest.raises(APIError) as error,
    ):
        github.latest_release("o/r")
    assert "token-secret" not in str(error.value)


def test_missing_release_checks_repository_access() -> None:
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(
            404 if request.url.path.endswith("latest") else 200, json={}
        )

    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        assert github.latest_release("o/r") is None
    assert requests == ["/repos/o/r/releases/latest", "/repos/o/r"]


def test_search_all_pages_and_stable_tie_order() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        second = request.url.params.get("page") == "2"
        numbers = [101] if second else list(range(100, 0, -1))
        return httpx.Response(
            200,
            json={
                "total_count": 101,
                "incomplete_results": False,
                "items": [pull_request(n) for n in numbers],
            },
            headers={}
            if second
            else {"Link": '<https://api.github.com/search/issues?page=2>; rel="next"'},
        )

    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        changes = github.pull_requests("o/r", SINCE, CUTOFF)
    assert tuple(change.identifier for change in changes) == tuple(
        f"#{number}" for number in range(1, 102)
    )


@pytest.mark.parametrize("incomplete", [False, True])
def test_search_splits_and_deduplicates_boundaries(incomplete: bool) -> None:
    queries: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            queries.append(query)
        full = query == queries[0]
        numbers = (
            []
            if full
            else list(range(1, 502))
            if query == queries[1]
            else list(range(501, 1002))
        )
        next_url = request.url.copy_set_param("page", str(page + 1))
        return httpx.Response(
            200,
            json={
                "total_count": (1 if incomplete else 1001) if full else len(numbers),
                "incomplete_results": full and incomplete,
                "items": [
                    pull_request(n) for n in numbers[(page - 1) * 100 : page * 100]
                ],
            },
            headers={"Link": f'<{next_url}>; rel="next"'}
            if page * 100 < len(numbers)
            else {},
        )

    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        changes = github.pull_requests("o/r", SINCE, CUTOFF)
    assert tuple(change.identifier for change in changes) == tuple(
        f"#{number}" for number in range(1, 1002)
    )
    assert len(queries) == 3
    assert all("merged:" in query for query in queries)


def test_split_search_detects_missing_results() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "total_count": 1001 if calls == 1 else 1,
                "incomplete_results": False,
                "items": [] if calls == 1 else [pull_request()],
            },
        )

    with (
        GitHub(
            "https://api.github.com", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(ChangelogError, match="completeness"),
    ):
        github.pull_requests("o/r", SINCE, CUTOFF)


def test_indivisible_search_fails() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"total_count": 1001, "incomplete_results": False, "items": []}
        )

    with (
        GitHub(
            "https://api.github.com", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(ChangelogError, match="complete"),
    ):
        github.pull_requests("o/r", SINCE, SINCE)


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/steal",
        "https://api.github.com:444/steal",
        "https://token@api.github.com/steal",
        "http://api.github.com/steal",
    ],
)
def test_cross_origin_pagination_never_sends_token(link: str) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], headers={"Link": f'<{link}>; rel="next"'})

    with (
        GitHub(
            "https://api.github.com", "secret", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(ChangelogError, match="origin"),
    ):
        github.commits("o/r", None, CUTOFF)
    assert len(requests) == 1


def test_redirect_is_not_followed() -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example"})

    with (
        GitHub(
            "https://api.github.com", "secret", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(APIError),
    ):
        github.latest_release("o/r")
    assert len(seen) == 1


def test_retries_only_safe_reads() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise httpx.ReadTimeout("secret", request=request)

    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        with pytest.raises(APIError):
            github.request("GET", "repos/o/r")
        with pytest.raises(APIError):
            github.request("POST", "repos/o/r/pulls", payload={})
    assert calls == ["GET", "GET", "GET", "POST"]


def test_transient_read_failure_can_recover() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return (
            httpx.Response(503, text="secret")
            if len(requests) == 1
            else httpx.Response(200, json={"published_at": "2026-01-01T00:00:00Z"})
        )

    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        assert github.latest_release("o/r") == SINCE
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/repos/o/r/releases/latest"),
        ("GET", "/repos/o/r/releases/latest"),
    ]


@pytest.mark.parametrize(
    "link",
    [
        "https://[broken/secret",
        "https://api.github.com:bad/secret",
        "https://api.github.com/\0secret",
    ],
)
def test_malformed_pagination_fails_before_another_request(link: str) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], headers={"Link": f'<{link}>; rel="next"'})

    with (
        GitHub(
            "https://api.github.com", "secret", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(ChangelogError, match="invalid pagination URL") as error,
    ):
        github.commits("o/r", SINCE, CUTOFF)
    assert len(requests) == 1
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"published_at": "nope"},
        {"published_at": 123},
        {"published_at": "2026-01-01T00:00:00"},
    ],
)
def test_invalid_release_payload(payload: object) -> None:
    with (
        GitHub(
            "https://api.github.com",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        ) as github,
        pytest.raises(ChangelogError),
    ):
        github.latest_release("o/r")


def test_commits_paginate_filter_and_preserve_multiline() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        second = "page=2" in str(request.url)
        messages = (
            ["second"]
            if second
            else ["first\n\nbody", "Merge branch 'main'", "Merge pull request #2"]
        )
        items = [
            {
                "sha": f"{'b' if second else 'a'}{i:06}",
                "html_url": "https://github.com/o/r/commit/abc",
                "commit": {"message": msg},
            }
            for i, msg in enumerate(messages)
        ]
        return httpx.Response(
            200,
            json=items,
            headers={}
            if second
            else {
                "Link": (
                    '<https://api.github.com/repos/o/r/commits?page=2>; rel="next"'
                )
            },
        )

    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(handle)
    ) as github:
        changes = github.commits("o/r", SINCE, CUTOFF)
    assert [change.title for change in changes] == ["first\n\nbody", "second"]


@pytest.mark.parametrize("numbers", [(1,), (1, 1)])
def test_search_rejects_missing_or_duplicate_results(numbers: tuple[int, ...]) -> None:
    with (
        GitHub(
            "https://api.github.com",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "total_count": 2,
                        "incomplete_results": False,
                        "items": [pull_request(number) for number in numbers],
                    },
                )
            ),
        ) as github,
        pytest.raises(ChangelogError, match="completeness"),
    ):
        github.pull_requests("o/r", SINCE, CUTOFF)


@pytest.mark.parametrize("count,incomplete", [(3, False), (2, True)])
def test_search_rejects_pages_that_change_during_collection(
    count: int, incomplete: bool
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        second = len(requests) == 2
        return httpx.Response(
            200,
            json={
                "total_count": count if second else 2,
                "incomplete_results": second and incomplete,
                "items": [pull_request(2 if second else 1)],
            },
            headers={} if second else {"Link": '<?page=2>; rel="next"'},
        )

    with (
        GitHub(
            "https://api.github.com", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(ChangelogError, match="changed during collection"),
    ):
        github.pull_requests("o/r", SINCE, CUTOFF)
    assert len(requests) == 2
    assert requests[1].url.params["page"] == "2"


def test_search_stops_after_ten_pages() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "total_count": 1000,
                "incomplete_results": False,
                "items": [pull_request(len(requests))],
            },
            headers={"Link": f'<?page={len(requests) + 1}>; rel="next"'},
        )

    with (
        GitHub(
            "https://api.github.com", transport=httpx.MockTransport(handle)
        ) as github,
        pytest.raises(ChangelogError, match="pagination limit"),
    ):
        github.pull_requests("o/r", SINCE, CUTOFF)
    assert len(requests) == 10


def test_search_after_cutoff_does_not_request_any_pages() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Search after the cutoff must not request any pages")

    with GitHub(
        "https://api.github.com", transport=httpx.MockTransport(unexpected)
    ) as github:
        assert github.pull_requests("o/r", CUTOFF, SINCE) == ()


def test_pagination_cycle_fails() -> None:
    with (
        GitHub(
            "https://api.github.com",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=[],
                    headers={
                        "Link": (
                            "<https://api.github.com/repos/o/r/commits?page=2>; "
                            'rel="next"'
                        )
                    },
                )
            ),
        ) as github,
        pytest.raises(ChangelogError, match="cycle"),
    ):
        github.commits("o/r", None, CUTOFF)


@pytest.mark.parametrize(
    "api_url", ["https://api.github.com", "https://api.github.com:443"]
)
def test_pagination_accepts_equivalent_https_default_ports(api_url: str) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[],
            headers={
                "Link": (
                    '<https://api.github.com:443/repos/o/r/commits?page=2>; rel="next"'
                ),
            }
            if len(requests) == 1
            else {},
        )

    with GitHub(api_url, "secret", transport=httpx.MockTransport(handle)) as github:
        assert github.commits("o/r", SINCE, CUTOFF) == ()
    assert len(requests) == 2
    assert all(
        request.headers["Authorization"] == "Bearer secret" for request in requests
    )
