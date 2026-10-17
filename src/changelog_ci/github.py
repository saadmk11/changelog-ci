"""GitHub API requests and pagination."""

import time
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import TypeVar
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from .errors import APIError, ChangelogError
from .models import Change, Model

T = TypeVar("T")


class Payload(Model):
    """GitHub response fields; additional fields are ignored."""

    model_config = ConfigDict(extra="ignore")


class Release(Payload):
    """Latest release timestamp."""

    published_at: AwareDatetime


class Label(Payload):
    """A GitHub label."""

    name: str


class PullRequest(Payload):
    """A merged pull request returned by search."""

    number: int = Field(gt=0)
    title: str
    html_url: str
    labels: tuple[Label, ...]
    created_at: AwareDatetime


class SearchPage(Payload):
    """A search page and its completeness indicators."""

    total_count: int = Field(ge=0)
    incomplete_results: bool
    items: tuple[PullRequest, ...]


class CommitData(Payload):
    """The commit message returned by GitHub."""

    message: str


class Commit(Payload):
    """A commit returned by GitHub."""

    sha: str = Field(min_length=7)
    html_url: str
    commit: CommitData


def decode(response: httpx.Response, adapter: TypeAdapter[T]) -> T:
    """Validate a response without echoing the response body in errors."""
    try:
        return adapter.validate_json(response.content, strict=True)
    except ValidationError as exc:
        raise ChangelogError("GitHub returned an invalid response.") from exc


def timestamp(value: datetime) -> str:
    """Use UTC, second-resolution timestamps in GitHub queries."""
    if value.tzinfo is None:
        raise ChangelogError("GitHub returned a timestamp without a timezone.")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class GitHub:
    """A synchronous GitHub API client."""

    def __init__(
        self,
        api_url: str,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Configure the API origin, token and request timeouts."""
        self.api_url = api_url.rstrip("/")
        self.origin = urlsplit(self.api_url)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> "GitHub":
        """Return the API client."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the HTTP client."""
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        payload: dict[str, object] | None = None,
        missing_ok: bool = False,
    ) -> httpx.Response:
        """Request a trusted API URL, retrying transient GET failures."""
        url = path if "://" in path else f"{self.api_url}/{path.lstrip('/')}"
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError as exc:
            raise ChangelogError("GitHub returned an invalid pagination URL.") from exc
        if (
            (
                parsed.scheme,
                parsed.hostname,
                parsed.port if parsed.port is not None else 443,
            )
            != (
                self.origin.scheme,
                self.origin.hostname,
                self.origin.port if self.origin.port is not None else 443,
            )
            or parsed.username
            or parsed.password
        ):
            raise ChangelogError(
                "GitHub pagination attempted to leave the trusted API origin."
            )
        for attempt in range(3 if method == "GET" else 1):
            try:
                response = self.client.request(method, url, params=params, json=payload)
            except httpx.InvalidURL as exc:
                raise ChangelogError(
                    "GitHub returned an invalid pagination URL."
                ) from exc
            except httpx.HTTPError as exc:
                if method == "GET" and attempt < 2:
                    time.sleep(0.1 * (2**attempt))
                    continue
                raise APIError("transport") from exc
            if (
                method == "GET"
                and response.status_code in {500, 502, 503, 504}
                and attempt < 2
            ):
                time.sleep(0.1 * (2**attempt))
                continue
            if response.is_success or (missing_ok and response.status_code == 404):
                return response
            raise APIError("read" if method == "GET" else "write", response.status_code)
        raise APIError("transport")

    def latest_release(self, repository: str) -> datetime | None:
        """Return the latest release date, or None for an accessible unreleased repo."""
        response = self.request(
            "GET", f"repos/{repository}/releases/latest", missing_ok=True
        )
        if response.status_code == 404:
            self.request("GET", f"repos/{repository}")
            return None
        released = decode(response, TypeAdapter(Release)).published_at
        timestamp(released)
        return released

    def _next(self, response: httpx.Response, seen: set[str]) -> str | None:
        link = response.links.get("next", {}).get("url")
        if not link:
            return None
        try:
            url = urljoin(str(response.url), link)
        except ValueError as exc:
            raise ChangelogError("GitHub returned an invalid pagination URL.") from exc
        if url in seen:
            raise ChangelogError("GitHub returned a pagination cycle.")
        seen.add(url)
        return url

    def pull_requests(
        self, repository: str, since: datetime | None, cutoff: datetime
    ) -> tuple[Change, ...]:
        """Split capped/incomplete searches and deduplicate inclusive boundaries."""
        start = since or datetime(1970, 1, 1, tzinfo=UTC)
        if start > cutoff:
            return ()

        def collect(low: datetime, high: datetime, depth: int = 0) -> list[PullRequest]:
            query = (
                f"repo:{repository} is:pr is:merged "
                f"merged:{timestamp(low)}..{timestamp(high)}"
            )
            response = self.request(
                "GET",
                "search/issues",
                params={"q": query, "sort": "created", "order": "asc", "per_page": 100},
            )
            page = decode(response, TypeAdapter(SearchPage))
            if page.total_count > 1000 or page.incomplete_results:
                seconds = int((high - low).total_seconds())
                if seconds <= 1 or depth >= 40:
                    raise ChangelogError(
                        "Cannot establish complete GitHub search results "
                        "within a one-second interval."
                    )
                middle = low + timedelta(seconds=seconds // 2)
                items = collect(low, middle, depth + 1) + collect(
                    middle, high, depth + 1
                )
                if (
                    not page.incomplete_results
                    and len({item.number for item in items}) != page.total_count
                ):
                    raise ChangelogError(
                        "GitHub search changed during collection; "
                        "completeness cannot be established."
                    )
                return items
            items = list(page.items)
            expected = page.total_count
            seen: set[str] = set()
            while link := self._next(response, seen):
                if len(seen) >= 10:
                    raise ChangelogError("GitHub search exceeded its pagination limit.")
                response = self.request("GET", link)
                page = decode(response, TypeAdapter(SearchPage))
                if page.incomplete_results or page.total_count != expected:
                    raise ChangelogError(
                        "GitHub search changed during collection; retry the run."
                    )
                items.extend(page.items)
            if len({item.number for item in items}) != expected:
                raise ChangelogError(
                    "GitHub search returned fewer or duplicate results; "
                    "completeness cannot be established."
                )
            return items

        unique = {item.number: item for item in collect(start, cutoff)}
        ordered = sorted(
            unique.values(), key=lambda item: (item.created_at, item.number)
        )
        return tuple(
            Change(
                identifier=f"#{item.number}",
                title=item.title,
                url=item.html_url,
                labels=tuple(label.name for label in item.labels),
            )
            for item in ordered
        )

    def commits(
        self, repository: str, since: datetime | None, cutoff: datetime
    ) -> tuple[Change, ...]:
        """Read every commit page, preserving GitHub's newest-first order."""
        params: dict[str, str | int] = {"per_page": 100, "until": timestamp(cutoff)}
        if since:
            params["since"] = timestamp(since)
        response = self.request("GET", f"repos/{repository}/commits", params=params)
        changes: dict[str, Change] = {}
        seen: set[str] = set()
        while True:
            for item in decode(response, TypeAdapter(list[Commit])):
                if not item.commit.message.startswith(
                    ("Merge pull request #", "Merge branch")
                ):
                    changes.setdefault(
                        item.sha,
                        Change(
                            identifier=item.sha[:7],
                            title=item.commit.message,
                            url=item.html_url,
                        ),
                    )
            link = self._next(response, seen)
            if not link:
                break
            response = self.request("GET", link)
        return tuple(changes.values())
