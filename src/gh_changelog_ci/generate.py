"""Collect and render changelog entries without writing files."""

from .errors import APIError
from .github import GitHub
from .models import GenerationRequest, GenerationResult, Source
from .render import render


def generate(request: GenerationRequest, github: GitHub) -> GenerationResult:
    """Collect changes and return the requested format plus Markdown."""
    since = github.latest_release(request.repository)
    collect = (
        github.pull_requests
        if request.settings.changelog_type == Source.PULL_REQUEST
        else github.commits
    )
    try:
        changes = collect(request.repository, since, request.cutoff)
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
