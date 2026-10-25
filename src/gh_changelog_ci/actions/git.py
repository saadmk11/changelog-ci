"""Git checkout, commit and push operations."""

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from ..errors import ConfigurationError, GitError
from ..files import output_path
from ..models import Settings
from . import require_github_actions


def branch_component(version: str) -> str:
    """Convert a release label to a valid branch-name component."""
    component = re.sub(r"[^A-Za-z0-9._-]+", "-", version)
    return re.sub(r"\.{2,}", "-", component).strip(".-") or "release"


class Git:
    """A checkout used to commit changelog updates."""

    def __init__(self, workspace: Path, settings: Settings) -> None:
        """Bind the checkout, author identity and changelog path."""
        require_github_actions()
        self.workspace = workspace.resolve(strict=True)
        self.settings = settings
        self.path = output_path(
            self.workspace, settings.changelog_filename, require_parent=False
        )
        self.relative = self.path.relative_to(self.workspace).as_posix()

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run with per-command identity, disabled hooks, and safe diagnostics."""
        require_github_actions()
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                (
                    "GIT_DIR",
                    "GIT_WORK_TREE",
                    "GIT_INDEX",
                    "GIT_OBJECT",
                    "GIT_ALTERNATE",
                    "GIT_EXTERNAL_DIFF",
                    "GIT_LITERAL_PATHSPECS",
                    "GIT_GLOB_PATHSPECS",
                    "GIT_NOGLOB_PATHSPECS",
                    "GIT_ICASE_PATHSPECS",
                )
            )
        }
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": self.settings.committer_username,
                "GIT_AUTHOR_EMAIL": self.settings.committer_email,
                "GIT_COMMITTER_NAME": self.settings.committer_username,
                "GIT_COMMITTER_EMAIL": self.settings.committer_email,
            }
        )
        # check-ignore accepts filenames, but rejects Git's literal pathspec magic.
        if args[0] != "check-ignore":
            env["GIT_LITERAL_PATHSPECS"] = "1"
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={self.workspace}",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "commit.gpgSign=false",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "protocol.ext.allow=never",
                *args,
            ],
            cwd=self.workspace,
            env=env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if check and result.returncode:
            raise GitError(args[0], result.returncode)
        return result

    def branch(self, value: str) -> str:
        """Reject options, ref expressions and invalid destination branches."""
        if (
            value.startswith(("-", "refs/", "@"))
            or "\0" in value
            or self.run("check-ref-format", "--branch", value, check=False).returncode
        ):
            raise ConfigurationError("Invalid destination branch.")
        return value

    def validate(
        self,
        repository: str,
        *,
        hostname: str = "github.com",
    ) -> None:
        """Validate the checkout and remote before network or file mutations."""
        root = self.run("rev-parse", "--show-toplevel").stdout.strip()
        if Path(root).resolve() != self.workspace:
            raise ConfigurationError("Workspace must be the repository root.")
        for command in (
            ("get-url", "--all", "origin"),
            ("get-url", "--push", "--all", "origin"),
        ):
            remotes = self.run("remote", *command).stdout.splitlines()
            if len(remotes) != 1:
                raise ConfigurationError(
                    "Expected exactly one origin fetch/push destination."
                )
            remote = remotes[0]
            try:
                parsed = urlsplit(remote)
            except ValueError as exc:
                raise ConfigurationError("Invalid origin URL.") from exc
            if parsed.scheme in {"https", "ssh"}:
                remote_path = parsed.path.lstrip("/")
                remote_host = parsed.hostname
            elif re.fullmatch(r"[^\s@]+@[^\s:]+:[^\s]+", remote):
                remote_path = remote.split(":", 1)[1]
                remote_host = remote.split("@", 1)[1].split(":", 1)[0]
            else:
                raise ConfigurationError("Origin must use HTTPS or SSH.")
            if (
                remote_host != hostname
                or remote_path.removesuffix(".git").casefold() != repository.casefold()
            ):
                raise ConfigurationError(
                    "Origin does not match the intended destination repository."
                )
        self.validate_target()

    def validate_target(self) -> None:
        """Require a safe output path and no unfinished Git operation."""
        self.path = output_path(
            self.workspace, self.settings.changelog_filename, require_parent=False
        )
        if self.run("ls-files", "--unmerged").stdout:
            raise ConfigurationError("Repository has unresolved merge conflicts.")
        git_directory = Path(self.run("rev-parse", "--absolute-git-dir").stdout.strip())
        if any(
            (git_directory / name).exists()
            for name in (
                "MERGE_HEAD",
                "CHERRY_PICK_HEAD",
                "REVERT_HEAD",
                "rebase-merge",
                "rebase-apply",
                "sequencer",
            )
        ):
            raise ConfigurationError(
                "Finish or abort the current Git operation "
                "before generating a changelog."
            )
        ignored = self.run(
            "check-ignore", "--quiet", "--", self.relative, check=False
        ).returncode
        if ignored not in {0, 1}:
            raise GitError("check-ignore", ignored)
        if ignored == 0:
            raise ConfigurationError(
                "The changelog is ignored by Git; "
                "refusing to write an uncommittable file."
            )

    def _changed_paths(self, *revisions: str) -> set[str]:
        """Return paths changed since a commit or between two commits."""
        result = self.run(
            "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", *revisions
        )
        return set(result.stdout.split("\0")) - {""}

    def prepare(self, base: str, destination: str, *, new: bool) -> None:
        """Fetch a real branch; safely leave detached merge refs and shallow clones."""
        self.branch(base)
        self.branch(destination)
        self.validate_target()
        local_changes = self._changed_paths("HEAD")
        shallow = (
            self.run("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
        )
        self.run(
            "fetch",
            *(["--unshallow"] if shallow else []),
            "--no-tags",
            "origin",
            f"refs/heads/{base}",
        )
        existing = (
            not new
            and self.run(
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{destination}",
                check=False,
            ).returncode
            == 0
        )
        # Checkout can silently restore local deletions. Check every changed path
        # against both the intermediate local branch and the fetched destination.
        if local_changes:
            revisions = (
                ("FETCH_HEAD", f"refs/heads/{destination}")
                if existing
                else ("FETCH_HEAD",)
            )
            for revision in revisions:
                if local_changes & self._changed_paths("HEAD", revision):
                    raise ConfigurationError(
                        "The destination differs for files with local changes; "
                        "refusing to overwrite them."
                    )
        if existing:
            self.run("checkout", "--no-guess", "--no-overwrite-ignore", destination)
            # Preserve local commits and fail on divergence.
            self.run("merge", "--ff-only", "--no-overwrite-ignore", "FETCH_HEAD")
            if (
                self.run("rev-parse", "HEAD").stdout
                != self.run("rev-parse", "FETCH_HEAD").stdout
            ):
                raise ConfigurationError(
                    "Destination branch has unpushed local commits; "
                    "refusing to include them."
                )
        else:
            self.run(
                "checkout",
                "--no-guess",
                "--no-overwrite-ignore",
                "-b",
                destination,
                "FETCH_HEAD",
            )
        self.validate_target()

    def commit(self, branch: str, message: str) -> bool:
        """Commit only the changelog, preserving unrelated staged and unstaged work."""
        self.branch(branch)
        self.validate_target()
        self.run("add", "--", self.relative)
        difference = self.run(
            "diff",
            "--cached",
            "--quiet",
            "--no-ext-diff",
            "--",
            self.relative,
            check=False,
        ).returncode
        if difference not in {0, 1}:
            raise GitError("diff", difference)
        if not difference:
            return False
        self.run("commit", "--only", "-m", message, "--", self.relative)
        self.run("push", "origin", f"HEAD:refs/heads/{branch}")
        return True
