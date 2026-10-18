from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter

from gh_changelog_ci.config import validate
from gh_changelog_ci.models import Change, Group, GroupBy, Settings
from gh_changelog_ci.render import render


class Entry(BaseModel):
    title: str = ""
    message: str = ""
    number: int = 0
    sha: str = ""
    url: str
    labels: list[str] = []


class Golden(BaseModel):
    options: dict[str, object]
    entries: list[Entry]
    version: str
    expected: str


GOLDENS = TypeAdapter(list[Golden]).validate_json(
    (Path(__file__).parents[1] / "fixtures/legacy/render.json").read_bytes()
)


@pytest.mark.parametrize("golden", GOLDENS)
def test_original_rendering(golden: Golden) -> None:
    settings = validate(golden.options)
    changes = tuple(
        Change(
            identifier=f"#{e.number}" if e.number else e.sha[:7],
            title=e.title or e.message,
            url=e.url,
            labels=tuple(e.labels),
        )
        for e in golden.entries
    )
    assert (
        render(changes, settings, golden.version, rst=settings.rst, legacy=True)
        == golden.expected
    )


def test_exclusions_without_groups_only_corrected_for_standalone() -> None:
    change = Change(
        identifier="#1", title="Skip", url="https://example.com", labels=("skip",)
    )
    settings = Settings(exclude_labels=("skip",))
    assert "Skip" not in render((change,), settings, "1")
    assert "Skip" in render((change,), settings, "1", legacy=True)


@pytest.mark.parametrize("rst", [False, True])
def test_empty_changes(rst: bool) -> None:
    assert render((), Settings(), "1", rst=rst) == ""


@pytest.mark.parametrize("rst", [False, True])
@pytest.mark.parametrize("include_unmatched", [False, True])
def test_issue_types_group_once_in_configured_order(
    rst: bool, include_unmatched: bool
) -> None:
    settings = Settings(
        group_by=GroupBy.ISSUE_TYPE,
        group_config=(
            Group(title="Features", labels=("bug",), issue_types=("Feature",)),
            Group(title="Fixes", labels=("feature",), issue_types=("Bug",)),
        ),
        exclude_labels=("skip",),
        include_unlabeled_changes=include_unmatched,
        unlabeled_group_title="Unmatched",
    )
    changes = tuple(
        Change(
            identifier=f"#{i}",
            title=title,
            url=f"https://github.com/o/r/pull/{i}",
            labels=labels,
            issue_types=types,
        )
        for i, (title, labels, types) in enumerate(
            [
                ("Both types", (), ("Bug", "Feature")),
                ("Bug only", ("bug",), ("Bug",)),
                ("Untyped", ("feature",), ()),
                ("Unknown type", (), ("Task",)),
                ("Excluded", ("skip",), ("Bug",)),
            ],
            start=1,
        )
    )
    result = render(changes, settings, "1", rst=rst)
    assert result.count("Both types") == 1
    assert result.index("Features") < result.index("Both types")
    assert result.index("Both types") < result.index("Fixes")
    assert result.index("Fixes") < result.index("Bug only")
    assert "Excluded" not in result
    assert ("Unmatched" in result) is include_unmatched
    assert ("Untyped" in result) is include_unmatched
    assert ("Unknown type" in result) is include_unmatched


def test_default_label_grouping_ignores_linked_issue_types() -> None:
    changes = (Change(identifier="#1", title="Fix", url="url", issue_types=("Bug",)),)
    settings = Settings(
        group_config=(Group(title="Fixes", labels=("bug",), issue_types=("Bug",)),)
    )
    result = render(changes, settings, "1")
    assert "Fixes" not in result
    assert "Other Changes" in result
