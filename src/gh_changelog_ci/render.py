"""Format changelogs as Markdown or reStructuredText."""

from .models import Change, Group, GroupBy, Settings, Source


def render(
    changes: tuple[Change, ...],
    settings: Settings,
    version: str,
    *,
    rst: bool = False,
    legacy: bool = False,
) -> str:
    """Format changes in order, assigning each to its first matching group."""
    if not changes:
        return ""
    header = f"{settings.header_prefix} {version}"
    result = f"{header}\n{'=' * len(header)}\n\n" if rst else f"# {header}\n\n"

    def lines(items: tuple[Change, ...]) -> str:
        return "".join(
            f"* `{c.identifier} <{c.url}>`__: {c.title}\n"
            if rst
            else f"* [{c.identifier}]({c.url}): {c.title}\n"
            for c in items
        )

    if settings.changelog_type == Source.COMMIT_MESSAGE:
        return result + lines(changes)
    remaining = tuple(
        c
        for c in changes
        if (legacy and not settings.group_config)
        or not set(c.labels).intersection(settings.exclude_labels)
    )
    if not settings.group_config:
        return result + lines(remaining)
    groups: tuple[Group | None, ...] = settings.group_config + (
        (None,) if settings.include_unlabeled_changes else ()
    )
    for group in groups:
        unmatched = group is None
        title = group.title if group else settings.unlabeled_group_title
        items = tuple(
            c
            for c in remaining
            if group is None
            or (
                set(c.issue_types).intersection(group.issue_types)
                if settings.group_by == GroupBy.ISSUE_TYPE
                else set(c.labels).intersection(group.labels)
            )
        )
        remaining = tuple(c for c in remaining if c not in items)
        if items:
            if rst:
                # Configured RST group underlines include one leading space.
                result += f"\n{title}\n{'' if unmatched else ' '}{'-' * len(title)}\n\n"
            else:
                result += f"\n#### {title}\n\n"
            result += lines(items)
    return result
