import re
from collections.abc import Sequence

import httpx


def pull_request_event(
    *,
    title: str = "Release v2.0.0",
    number: int = 9,
    head: str = "main",
    head_repository: str | None = "o/r",
) -> dict[str, object]:
    return {
        "number": number,
        "repository": {"full_name": "o/r", "default_branch": "main"},
        "pull_request": {
            "title": title,
            "head": {
                "ref": head,
                "repo": {"full_name": head_repository} if head_repository else None,
            },
            "base": {"ref": "main", "repo": {"full_name": "o/r"}},
        },
    }


def pull_request(number: int = 1, *, labels: tuple[str, ...] = ()) -> dict[str, object]:
    return {
        "number": number,
        "title": f"Change {number}",
        "html_url": f"https://github.com/o/r/pull/{number}",
        "labels": [{"name": label} for label in labels],
        "created_at": "2026-01-01T00:00:00Z",
    }


def linked_issues(
    *types: str | None,
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> dict[str, object]:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "closingIssuesReferences": {
                        "nodes": [
                            {"issueType": {"name": name} if name else None}
                            for name in types
                        ],
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                    }
                }
            }
        }
    }


def response(
    request: httpx.Request, *, changes: Sequence[dict[str, object]] | None = None
) -> httpx.Response:
    path = request.url.path.removeprefix("/api/v3")
    if request.method == "GET" and path == "/repos/o/r/releases/latest":
        return httpx.Response(200, json={"published_at": "2026-01-01T00:00:00Z"})
    if request.method == "GET" and path == "/search/issues":
        items = changes if changes is not None else (pull_request(),)
        return httpx.Response(
            200,
            json={
                "total_count": len(items),
                "incomplete_results": False,
                "items": list(items),
            },
        )
    if request.method == "GET" and path == "/repos/o/r/commits":
        return httpx.Response(
            200,
            json=[
                {
                    "sha": "abcdef01234",
                    "html_url": "https://github.com/o/r/commit/abcdef01234",
                    "commit": {"message": "Fix a bug"},
                }
            ],
        )
    if request.method == "POST" and (
        path == "/repos/o/r/pulls"
        or re.fullmatch(r"/repos/o/r/issues/[1-9]\d*/comments", path)
    ):
        return httpx.Response(
            201, json={"number": 9, "html_url": "https://github.com/o/r/pull/9"}
        )
    raise AssertionError(f"Unexpected GitHub request: {request.method} {path}")
