from pathlib import Path

import pytest

from changelog_ci.actions.git import Git, branch_component
from changelog_ci.errors import ConfigurationError, GitError
from changelog_ci.files import write_atomic
from changelog_ci.models import Settings
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
    "filename", ["Change log.md", "Café 🐛.md", "-release.md", "[notes].md"]
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


@pytest.mark.parametrize("state", ["staged", "dirty", "untracked"])
def test_refuses_existing_work(repository: tuple[Path, Path], state: str) -> None:
    workspace, _ = repository
    if state == "staged":
        (workspace / "other.txt").write_text("staged work")
        command(workspace, "add", "--", "other.txt")
    elif state == "dirty":
        (workspace / "CHANGELOG.md").write_text("local changelog")
    else:
        (workspace / "new.md").write_text("untracked changelog")
    git = Git(
        workspace,
        Settings(
            changelog_filename="new.md" if state == "untracked" else "CHANGELOG.md"
        ),
    )
    before = command(workspace, "status", "--porcelain")
    with pytest.raises(ConfigurationError):
        git.validate("o/r")
    assert command(workspace, "status", "--porcelain") == before


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
    assert branch_component("v2.0.0 (2026/10/16)") == "v2.0.0-2026-10-16"
    assert branch_component("v2.0.0") == "v2.0.0"
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
    with pytest.raises(GitError):
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
