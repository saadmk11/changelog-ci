from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter

from changelog_ci.config import validate
from changelog_ci.models import Change, Settings
from changelog_ci.render import render


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
