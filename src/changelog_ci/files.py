"""Changelog paths, diffs and atomic file updates."""

import difflib
import os
import stat
import tempfile
from pathlib import Path

from .errors import ChangelogError, ConfigurationError


def file_diff(filename: str, old: bytes, new: bytes) -> str:
    """Return a unified diff of the changelog update."""
    return "".join(
        difflib.unified_diff(
            old.decode("utf-8").splitlines(keepends=True),
            new.decode("utf-8").splitlines(keepends=True),
            fromfile=filename,
            tofile=filename,
        )
    )


def output_path(workspace: Path, filename: str, *, require_parent: bool = True) -> Path:
    """Validate the output path, requiring its parent for file writes."""
    root = workspace.resolve(strict=True)
    if not root.is_dir():
        raise ConfigurationError("Workspace must be a directory.")
    path = root / filename
    if (
        ".." in path.parts
        or not path.is_relative_to(root)
        or any(
            part.rstrip(" .").casefold() == ".git"
            for part in path.relative_to(root).parts
        )
    ):
        raise ConfigurationError(
            "Changelog path must stay inside the workspace, outside .git."
        )
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ConfigurationError("Changelog path must not traverse symlinks.")
    if (require_parent and not path.parent.is_dir()) or (
        path.exists() and not path.is_file()
    ):
        raise ConfigurationError(
            "Changelog parent must exist and output must be a regular file."
        )
    return path


def prepend_content(path: Path, section: str) -> tuple[bytes, bytes]:
    """Keep existing bytes and choose the existing file's newline style."""
    old = path.read_bytes() if path.exists() else b""
    if not section:
        return old, old
    newline = "\r\n" if b"\r\n" in old else "\n"
    addition = section.replace("\r\n", "\n").replace("\n", newline).encode("utf-8")
    return old, addition + (newline.encode() * 2 + old if old else b"")


def write_atomic(path: Path, content: bytes) -> None:
    """Replace only the changelog, retaining existing permission bits."""
    temporary: str | None = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except OSError as exc:
        raise ChangelogError("Could not write the changelog file.") from exc
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
