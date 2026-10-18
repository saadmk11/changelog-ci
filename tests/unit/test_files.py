import os
import stat
from pathlib import Path

import pytest

from gh_changelog_ci.errors import ChangelogError, ConfigurationError
from gh_changelog_ci.files import output_path, prepend_content, write_atomic


@pytest.mark.parametrize(
    "old,expected",
    [
        pytest.param(b"", b"# New\n\n* change\n", id="empty"),
        pytest.param(b"existing\n", b"# New\n\n* change\n\n\nexisting\n", id="lf"),
        pytest.param(
            b"existing\r\n",
            b"# New\r\n\r\n* change\r\n\r\n\r\nexisting\r\n",
            id="crlf",
        ),
        pytest.param(
            b"\xff\xfeold", b"# New\n\n* change\n\n\n\xff\xfeold", id="binary"
        ),
    ],
)
def test_prepend_preserves_bytes(old: bytes, expected: bytes, tmp_path: Path) -> None:
    path = tmp_path / "Change log.md"
    path.write_bytes(old)
    before, after = prepend_content(path, "# New\n\n* change\n")
    assert before == old
    assert after == expected
    write_atomic(path, after)
    assert path.read_bytes() == expected


def test_empty_section_does_not_change_content(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_bytes(b"existing\r\n")
    assert prepend_content(path, "") == (b"existing\r\n", b"existing\r\n")
    assert path.read_bytes() == b"existing\r\n"


@pytest.mark.parametrize(
    "name",
    [
        "../outside.md",
        ".git/config.md",
        ".GIT/config.md",
        ".git. /config.md",
        "missing/output.md",
    ],
)
def test_unsafe_paths(name: str, tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        output_path(tmp_path, name)


@pytest.mark.parametrize("require_parent", [False, True])
def test_symlink_parent_and_file(tmp_path: Path, require_parent: bool) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
        (tmp_path / "alias.md").symlink_to(target / "missing.md")
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Symlinks require Windows developer mode")
        raise
    for name in ("link/file.md", "alias.md"):
        with pytest.raises(ConfigurationError):
            output_path(tmp_path, name, require_parent=require_parent)


def test_atomic_failure_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("original")

    def fail(source: str, destination: Path) -> None:
        raise OSError("failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(ChangelogError):
        write_atomic(path, b"new")
    assert path.read_text() == "original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_preserve_permissions(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("original")
    path.chmod(0o640)
    write_atomic(path, b"new")
    assert path.read_bytes() == b"new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.parametrize("require_parent", [False, True])
def test_workspace_must_be_a_directory(tmp_path: Path, require_parent: bool) -> None:
    file = tmp_path / "file"
    file.write_text("keep")
    with pytest.raises(ConfigurationError, match="Workspace must be a directory"):
        output_path(file, "CHANGELOG.md", require_parent=require_parent)
    assert file.read_text() == "keep"
