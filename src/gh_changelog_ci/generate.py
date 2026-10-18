"""Collect and render changelog entries without writing files."""

from .errors import APIError
from .github import GitHub
from .models import GenerationRequest, GenerationResult, GroupBy, Source
from .render import render


def generate(request: GenerationRequest, github: GitHub) -> GenerationResult:
    """Collect changes and return the requested format plus Markdown."""
    since = github.latest_release(request.repository)
    try:
        if request.settings.changelog_type == Source.PULL_REQUEST:
            include_issue_types = (
                request.settings.group_by == GroupBy.ISSUE_TYPE
                and bool(request.settings.group_config)
            )
            changes = github.pull_requests(
                request.repository,
                since,
                request.cutoff,
                include_issue_types=include_issue_types,
                exclude_labels=(
                    request.settings.exclude_labels if include_issue_types else ()
                ),
            )
        else:
            changes = github.commits(request.repository, since, request.cutoff)
    except APIError as exc:
        raise APIError("collection", exc.status) from exc
    markdown = render(changes, request.settings, request.version, legacy=request.legacy)
    section = (
        render(
            changes, request.settings, request.version, rst=True, legacy=request.legacy
        )
        if request.settings.rst
        else markdown
    )
    return GenerationResult(section=section, markdown=markdown, changes=changes)
