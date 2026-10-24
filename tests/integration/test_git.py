import subprocess
from pathlib import Path

import pytest

from gh_changelog_ci.actions.git import Git, branch_component
from gh_changelog_ci.errors import ConfigurationError, GitError
from gh_changelog_ci.files import write_atomic
from gh_changelog_ci.models import Settings
from tests.git import command

pytestmark = pytest.mark.actions


@pytest.mark.parametrize("shallow", [False, True])
def test_detached_checkout_commit_push_and_rerun(
    repository: tuple[Path, Path], tmp_path: Path, shallow: bool
) -> None:
    _, remote = repository
    workspace = tmp_path / "clone"
    command(
        tmp_path,
        "clone",
        *(["--depth=1"] if shallow else []),
        remote.as_uri(),
        str(workspace),
    )
    command(workspace, "remote", "set-url", "origin", "git@github.com:o/r.git")
    command(workspace, "checkout", "--detach")
    git = Git(workspace, Settings())
    git.validate("o/r")
    git.prepare("main", "main", new=False)
    write_atomic(git.path, b"new\n\nold\n")
    assert git.commit("main", "Release")
    assert command(remote, "show", "main:CHANGELOG.md") == "new\n\nold"
    assert not git.commit("main", "No changes")
    git.prepare("main", "main", new=False)
    write_atomic(git.path, b"new\n\nnew\n\nold\n")
    assert git.commit("main", "Repeat")
    assert command(workspace, "rev-list", "--count", "HEAD") == "3"


@pytest.mark.parametrize(
    "filename",
    [
        "Change log.md",
        "Café 🐛.md",
        "-release.md",
        "[notes].md",
    ],
)
def test_preserves_unstaged_untracked_and_creates_new_branch(
    repository: tuple[Path, Path],
    filename: str,
) -> None:
    workspace, remote = repository
    (workspace / "other.txt").write_text("local work")
    (workspace / "untracked.txt").write_text("keep")
    git = Git(workspace, Settings(changelog_filename=filename))
    git.validate("o/r")
    git.prepare("main", "changelog-ci-v2-123", new=True)
    write_atomic(git.path, b"section")
    assert git.commit("changelog-ci-v2-123", "Message $(touch injected)")
    assert (workspace / "other.txt").read_text() == "local work"
    assert (workspace / "untracked.txt").read_text() == "keep"
    assert not (workspace / "injected").exists()
    assert command(remote, "show", f"changelog-ci-v2-123:{filename}") == "section"
    assert command(workspace, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize(
    "state,expected_codes,expected_content",
    [
        ("clean", (), "old\n"),
        ("modified", (" M",), "local changelog\n"),
        ("deleted", (" D",), None),
        ("staged", ("M ",), "local changelog\n"),
        ("staged-deletion", ("D ",), None),
        ("staged-then-deleted", ("MD",), None),
        ("staged-then-reverted", ("MM",), "old\n"),
        ("recreated-after-staged-deletion", ("D ", "??"), "recreated changelog\n"),
        ("partially-staged", ("MM",), "working changelog\n"),
        ("untracked", ("??",), "local changelog\n"),
        ("staged-new", ("A ",), "local changelog\n"),
        ("renamed", ("D ",), None),
    ],
)
def test_commits_only_changelog_with_existing_work(
    repository: tuple[Path, Path],
    state: str,
    expected_codes: tuple[str, ...],
    expected_content: str | None,
) -> None:
    workspace, remote = repository
    (workspace / "removed.txt").write_text("tracked file")
    command(workspace, "add", "--", "removed.txt")
    command(workspace, "commit", "-m", "Track removable file")
    command(workspace, "push", "origin", "main")
    filename = "new.md" if state in {"untracked", "staged-new"} else "CHANGELOG.md"
    path = workspace / filename
    if state in {
        "modified",
        "staged",
        "partially-staged",
        "untracked",
        "staged-new",
        "staged-then-deleted",
        "staged-then-reverted",
    }:
        path.write_text("local changelog\n")
    if state in {
        "staged",
        "partially-staged",
        "staged-new",
        "staged-then-deleted",
        "staged-then-reverted",
    }:
        command(workspace, "add", "--", filename)
    if state == "partially-staged":
        path.write_text("working changelog\n")
    elif state == "staged-then-reverted":
        path.write_text("old\n")
    if state in {"deleted", "staged-then-deleted"}:
        path.unlink()
    elif state in {"staged-deletion", "recreated-after-staged-deletion"}:
        command(workspace, "rm", "--", filename)
        if state == "recreated-after-staged-deletion":
            path.write_text("recreated changelog\n")
    elif state == "renamed":
        command(workspace, "mv", "--", filename, "renamed.md")
    assert (path.read_text() if path.exists() else None) == expected_content
    assert command(
        workspace,
        "status",
        "--porcelain",
        "-z",
        "--no-renames",
        "--",
        filename,
        strip=False,
    ) == "".join(f"{code} {filename}\0" for code in expected_codes)
    (workspace / "other.txt").write_text("staged work")
    command(workspace, "add", "--", "other.txt")
    (workspace / "other.txt").write_text("unstaged work")
    (workspace / "added.txt").write_text("staged addition")
    command(workspace, "add", "--", "added.txt")
    command(workspace, "rm", "--", "removed.txt")
    (workspace / "untracked.txt").write_text("untracked work")
    unrelated = ["other.txt", "added.txt", "removed.txt", "renamed.md"]
    index_before = command(
        workspace, "ls-files", "--stage", "-z", "--", *unrelated, strip=False
    )
    git = Git(workspace, Settings(changelog_filename=filename))
    git.validate("o/r")
    git.prepare("main", "notes", new=True)
    assert (path.read_text() if path.exists() else None) == expected_content
    new = "new section\n" + ("\n\n" + expected_content if expected_content else "")
    write_atomic(git.path, new.encode())
    assert git.commit("notes", "Update changelog")
    changed = command(remote, "diff", "--no-renames", "--name-only", "notes^", "notes")
    assert changed == filename
    assert git.path.read_text() == new
    assert command(remote, "show", f"notes:{filename}", strip=False) == new
    assert command(remote, "show", "main:CHANGELOG.md") == "old"
    assert (
        command(workspace, "ls-files", "--stage", "-z", "--", *unrelated, strip=False)
        == index_before
    )
    assert (workspace / "other.txt").read_text() == "unstaged work"
    assert (workspace / "added.txt").read_text() == "staged addition"
    assert not (workspace / "removed.txt").exists()
    assert (workspace / "untracked.txt").read_text() == "untracked work"
    head = command(workspace, "rev-parse", "HEAD")
    assert not git.commit("notes", "No changelog changes")
    assert command(workspace, "rev-parse", "HEAD") == head
    assert (
        command(workspace, "ls-files", "--stage", "-z", "--", *unrelated, strip=False)
        == index_before
    )


@pytest.mark.parametrize("new", [False, True])
def test_allows_non_overlapping_remote_changes(
    repository: tuple[Path, Path], tmp_path: Path, new: bool
) -> None:
    workspace, remote = repository
    other = tmp_path / "other"
    command(tmp_path, "clone", remote.as_uri(), str(other))
    (other / "new.txt").write_text("remote addition\n")
    command(other, "add", "--", "new.txt")
    command(other, "commit", "-m", "Add unrelated file")
    command(other, "push")
    (workspace / "CHANGELOG.md").write_text("local notes\n")
    (workspace / "other.txt").write_text("staged work\n")
    command(workspace, "add", "--", "other.txt")
    (workspace / "other.txt").write_text("unstaged work\n")
    before = command(
        workspace, "ls-files", "--stage", "-z", "--", "other.txt", strip=False
    )
    branch = "notes" if new else "main"
    git = Git(workspace, Settings())
    git.prepare("main", branch, new=new)
    assert (workspace / "new.txt").read_text() == "remote addition\n"
    assert git.path.read_text() == "local notes\n"
    assert (workspace / "other.txt").read_text() == "unstaged work\n"
    assert (
        command(workspace, "ls-files", "--stage", "-z", "--", "other.txt", strip=False)
        == before
    )
    write_atomic(git.path, b"new section\n\nlocal notes\n")
    assert git.commit(branch, "Update changelog")
    assert command(
        remote, "diff", "--name-only", "-z", f"{branch}^", branch, strip=False
    ) == ("CHANGELOG.md\0")


@pytest.mark.parametrize("new", [False, True])
@pytest.mark.parametrize("state", ["modified", "deleted", "staged", "staged-deletion"])
@pytest.mark.parametrize(
    "filename",
    [
        "CHANGELOG.md",
        "other.txt",
    ],
)
def test_refuses_switching_local_changes_to_a_different_base(
    repository: tuple[Path, Path], state: str, new: bool, filename: str
) -> None:
    workspace, remote = repository
    if not (workspace / filename).exists():
        (workspace / filename).write_text("old\n")
        command(workspace, "add", "--", filename)
        command(workspace, "commit", "-m", "Track file")
        command(workspace, "push", "origin", "main")
    command(workspace, "checkout", "-b", "release")
    path = workspace / filename
    path.write_text("release notes\n")
    command(workspace, "commit", "-am", "Release notes")
    command(workspace, "push", "origin", "release")
    command(workspace, "checkout", "main")
    if state in {"modified", "staged"}:
        path.write_text("local changelog\n")
        if state == "staged":
            command(workspace, "add", "--", filename)
    elif state == "deleted":
        path.unlink()
    else:
        command(workspace, "rm", "--", filename)
    before = path.read_bytes() if path.exists() else None
    index_before = command(workspace, "ls-files", "--stage", "-z")
    refs_before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    git = Git(workspace, Settings())
    git.validate("o/r")
    with pytest.raises(ConfigurationError, match="local changes"):
        git.prepare("release", "notes" if new else "release", new=new)
    assert (path.read_bytes() if path.exists() else None) == before
    assert command(workspace, "branch", "--show-current") == "main"
    assert command(workspace, "ls-files", "--stage", "-z") == index_before
    assert command(workspace, "show-ref") == refs_before
    assert command(remote, "show-ref") == remote_before


def test_checks_intermediate_local_branch_before_switching(
    repository: tuple[Path, Path],
) -> None:
    workspace, remote = repository
    command(workspace, "checkout", "-b", "release")
    path = workspace / "CHANGELOG.md"
    path.write_text("intermediate version\n")
    command(workspace, "commit", "-am", "Intermediate changelog")
    intermediate = command(workspace, "rev-parse", "HEAD")
    path.write_text("old\n")
    command(workspace, "commit", "-am", "Restore changelog")
    command(workspace, "push", "origin", "release")
    command(workspace, "checkout", "main")
    command(workspace, "branch", "-f", "release", intermediate)
    path.unlink()
    before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    with pytest.raises(ConfigurationError, match="local changes"):
        Git(workspace, Settings()).prepare("release", "release", new=False)
    assert not path.exists()
    assert command(workspace, "branch", "--show-current") == "main"
    assert command(workspace, "show-ref") == before
    assert command(remote, "show-ref") == remote_before


@pytest.mark.parametrize("ignored", [False, True])
@pytest.mark.parametrize("new", [False, True])
def test_checkout_preserves_untracked_and_ignored_obstructions(
    repository: tuple[Path, Path], tmp_path: Path, ignored: bool, new: bool
) -> None:
    workspace, remote = repository
    other = tmp_path / "other"
    command(tmp_path, "clone", remote.as_uri(), str(other))
    (other / "generated.txt").write_text("remote work")
    command(other, "add", "--", "generated.txt")
    command(other, "commit", "-m", "Track generated file")
    command(other, "push")
    if ignored:
        (workspace / ".gitignore").write_text("generated.txt\n")
    (workspace / "generated.txt").write_text("local work")
    before = command(workspace, "show-ref", "--heads")
    remote_before = command(remote, "show-ref")
    with pytest.raises(GitError):
        Git(workspace, Settings()).prepare("main", "notes" if new else "main", new=new)
    assert (workspace / "generated.txt").read_text() == "local work"
    assert command(workspace, "branch", "--show-current") == "main"
    assert command(workspace, "show-ref", "--heads") == before
    assert command(remote, "show-ref") == remote_before


@pytest.mark.parametrize("filename", ["CHANGELOG.md", "other.txt"])
@pytest.mark.parametrize("resolved", [False, True])
@pytest.mark.parametrize("operation", ["merge", "cherry-pick", "revert", "rebase"])
def test_refuses_unfinished_operation_without_changing_it(
    repository: tuple[Path, Path], filename: str, resolved: bool, operation: str
) -> None:
    workspace, remote = repository
    command(workspace, "checkout", "-b", "conflicting")
    (workspace / filename).write_text("branch change\n")
    command(workspace, "commit", "-am", "Branch change")
    command(workspace, "checkout", "main")
    (workspace / filename).write_text("main change\n")
    command(workspace, "commit", "-am", "Main change")
    command(workspace, "push", "origin", "main")
    with pytest.raises(subprocess.CalledProcessError):
        command(workspace, operation, "conflicting")
    if resolved:
        (workspace / filename).write_text("resolved change\n")
        command(workspace, "add", "--", filename)
    before = (workspace / filename).read_bytes()
    index_before = command(workspace, "ls-files", "--stage", "-z")
    refs_before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    state_name = {
        "merge": "MERGE_HEAD",
        "cherry-pick": "CHERRY_PICK_HEAD",
        "revert": "REVERT_HEAD",
        "rebase": "rebase-merge/head-name",
    }[operation]
    state_file = workspace / ".git" / state_name
    state_before = state_file.read_bytes()
    git = Git(workspace, Settings())
    with pytest.raises(ConfigurationError, match="current Git operation|unresolved"):
        git.prepare("main", "notes", new=True)
    assert (workspace / filename).read_bytes() == before
    assert command(workspace, "ls-files", "--stage", "-z") == index_before
    assert command(workspace, "show-ref") == refs_before
    assert command(remote, "show-ref") == remote_before
    assert state_file.read_bytes() == state_before


@pytest.mark.parametrize(
    "branch",
    [
        "--upload-pack=evil",
        "refs/tags/v1",
        "@{-1}",
        "bad..name",
        "bad name",
        "branch\nnext",
        "branch\0next",
    ],
)
def test_rejects_unsafe_branches(repository: tuple[Path, Path], branch: str) -> None:
    workspace, _ = repository
    with pytest.raises(ConfigurationError):
        Git(workspace, Settings()).branch(branch)


@pytest.mark.parametrize(
    "remote",
    [
        "ext::sh evil",
        "https://github.com/wrong/repo.git",
        "https://evil.example/o/r.git",
        "git@evil.example:o/r.git",
        "https://[invalid/o/r.git",
        "-invalid",
    ],
)
def test_rejects_unsafe_remotes(repository: tuple[Path, Path], remote: str) -> None:
    workspace, _ = repository
    command(workspace, "config", "remote.origin.url", remote)
    with pytest.raises(ConfigurationError):
        Git(workspace, Settings()).validate("o/r")


def test_requires_checkout_root(repository: tuple[Path, Path]) -> None:
    workspace, remote = repository
    nested = workspace / "nested"
    nested.mkdir()
    before = command(remote, "show-ref")
    with pytest.raises(ConfigurationError, match="repository root"):
        Git(nested, Settings()).validate("o/r")
    assert command(remote, "show-ref") == before
    assert not (nested / "CHANGELOG.md").exists()


@pytest.mark.parametrize("kind", ["url", "pushurl"])
def test_refuses_multiple_origin_destinations(
    kind: str, repository: tuple[Path, Path]
) -> None:
    workspace, remote = repository
    if kind == "pushurl":
        command(
            workspace,
            "config",
            "--add",
            "remote.origin.pushurl",
            "git@github.com:o/r.git",
        )
    command(
        workspace,
        "config",
        "--add",
        f"remote.origin.{kind}",
        "git@evil.example:o/r.git",
    )
    before = command(remote, "show-ref")
    with pytest.raises(ConfigurationError, match="exactly one origin"):
        Git(workspace, Settings()).validate("o/r")
    assert command(remote, "show-ref") == before
    assert (workspace / "CHANGELOG.md").read_text() == "old\n"


def test_disables_hooks_and_does_not_edit_global_config(
    repository: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, _ = repository
    global_config = tmp_path / "global"
    global_config.write_text("[user]\nname = Original\nemail = original@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    hooks = workspace / "hooks"
    hooks.mkdir()
    marker = workspace / "hook-ran"
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\ntouch hook-ran\nexit 1\n")
    hook.chmod(0o755)
    command(workspace, "config", "core.hooksPath", str(hooks))
    git = Git(workspace, Settings())
    write_atomic(git.path, b"new")
    assert git.commit("main", "Release")
    assert not marker.exists()
    assert (
        global_config.read_text()
        == "[user]\nname = Original\nemail = original@example.com\n"
    )
    assert (
        command(workspace, "log", "-1", "--format=%an <%ae>")
        == "github-actions[bot] <github-actions[bot]@users.noreply.github.com>"
    )


def test_non_fast_forward_push_does_not_overwrite_remote(
    repository: tuple[Path, Path], tmp_path: Path
) -> None:
    workspace, remote = repository
    other = tmp_path / "other"
    command(tmp_path, "clone", remote.as_uri(), str(other))
    (other / "other.txt").write_text("remote change")
    command(other, "commit", "-am", "Remote commit")
    command(other, "push")
    git = Git(workspace, Settings())
    write_atomic(git.path, b"new")
    with pytest.raises(GitError):
        git.commit("main", "Release")
    assert command(remote, "log", "-1", "--format=%s") == "Remote commit"


def test_sanitizes_only_branch_component() -> None:
    assert branch_component("v2.0.2 (2026/10/16)") == "v2.0.2-2026-10-16"
    assert branch_component("v2.0.2") == "v2.0.2"
    assert branch_component("???") == "release"


def test_refuses_ignored_target(repository: tuple[Path, Path]) -> None:
    workspace, _ = repository
    (workspace / ".gitignore").write_text("generated.md\n")
    with pytest.raises(ConfigurationError, match="ignored"):
        Git(workspace, Settings(changelog_filename="generated.md")).validate("o/r")
    assert not (workspace / "generated.md").exists()


def test_refuses_unpushed_local_commits(repository: tuple[Path, Path]) -> None:
    workspace, remote = repository
    (workspace / "other.txt").write_text("local commit")
    command(workspace, "commit", "-am", "Local work")
    before = command(workspace, "rev-parse", "HEAD")
    with pytest.raises(ConfigurationError, match="unpushed"):
        Git(workspace, Settings()).prepare("main", "main", new=False)
    assert command(workspace, "rev-parse", "HEAD") == before
    assert command(remote, "log", "-1", "--format=%s") == "Initial"


def test_branch_switch_refuses_overwriting_unrelated_work(
    repository: tuple[Path, Path], tmp_path: Path
) -> None:
    workspace, remote = repository
    other = tmp_path / "other"
    command(tmp_path, "clone", remote.as_uri(), str(other))
    (other / "other.txt").write_text("remote work")
    command(other, "commit", "-am", "Remote work")
    command(other, "push")
    (workspace / "other.txt").write_text("unsaved local work")
    with pytest.raises(ConfigurationError, match="local changes"):
        Git(workspace, Settings()).prepare("main", "release", new=True)
    assert (workspace / "other.txt").read_text() == "unsaved local work"
    assert command(workspace, "branch", "--show-current") == "main"


def test_existing_branch_is_never_replaced(repository: tuple[Path, Path]) -> None:
    workspace, _ = repository
    git = Git(workspace, Settings())
    git.prepare("main", "release", new=True)
    before = command(workspace, "show-ref")
    with pytest.raises(GitError):
        git.prepare("main", "release", new=True)
    assert command(workspace, "show-ref") == before


def test_output_directory_can_exist_only_on_destination_branch(
    repository: tuple[Path, Path],
) -> None:
    workspace, remote = repository
    command(workspace, "checkout", "-b", "release")
    (workspace / "releases").mkdir()
    (workspace / "releases/CHANGELOG.md").write_text("head notes\n")
    command(workspace, "add", "releases/CHANGELOG.md")
    command(workspace, "commit", "-m", "Add release directory")
    command(workspace, "push", "origin", "release")
    command(workspace, "checkout", "main")
    assert not (workspace / "releases").exists()
    git = Git(workspace, Settings(changelog_filename="releases/CHANGELOG.md"))
    git.validate("o/r")
    git.prepare("release", "release", new=False)
    write_atomic(git.path, b"new notes\n\nhead notes\n")
    assert git.commit("release", "Update release notes")
    assert command(remote, "show", "release:releases/CHANGELOG.md") == (
        "new notes\n\nhead notes"
    )
    assert command(remote, "show", "main:CHANGELOG.md") == "old"


def test_git_cannot_be_reused_outside_runner(
    repository: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, remote = repository
    git = Git(workspace, Settings())
    before = command(workspace, "show-ref")
    remote_before = command(remote, "show-ref")
    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(ConfigurationError, match="requires a GitHub Actions runner"):
        git.commit("main", "Release")
    assert command(workspace, "show-ref") == before
    assert command(remote, "show-ref") == remote_before
