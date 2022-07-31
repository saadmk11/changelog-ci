import subprocess

import github_action_utils as gha_utils  # type: ignore


def checkout_pull_request_branch(branch_name: str) -> None:
    """
    Checkout the PR branch and pull the latest changes.
    """
    with gha_utils.group(f"Checkout '{branch_name}' branch"):
        run_subprocess_command(
            ["git", "fetch", "--prune", "--unshallow", "origin", branch_name]
        )
        run_subprocess_command(["git", "checkout", branch_name])


def configure_git_author(username: str, email: str) -> None:
    """
    Configure the git author.
    """
    with gha_utils.group("Configure Git Author"):
        gha_utils.notice(f"Setting Git Commit User to '{username}'.")
        gha_utils.notice(f"Setting Git Commit email to '{email}'.")

        run_subprocess_command(["git", "config", "user.name", username])
        run_subprocess_command(["git", "config", "user.email", email])


def create_new_git_branch(base_branch_name: str, new_branch_name: str) -> None:
    """
    Create a new git branch from base branch.
    """
    with gha_utils.group(
        f"\nCreate New Branch ({base_branch_name} -> {new_branch_name})"
    ):
        run_subprocess_command(["git", "checkout", base_branch_name])
        run_subprocess_command(["git", "checkout", "-b", new_branch_name])


def git_commit_changelog(
    commit_message: str, changed_file: str, commit_author: str, commit_branch_name: str
) -> None:
    """
    Commit the changelog file.
    """
    with gha_utils.group(f"Commit Changelog ({changed_file})"):
        run_subprocess_command(["git", "add", changed_file])
        run_subprocess_command(
            ["git", "commit", f"--author={commit_author}", "-m", commit_message]
        )
        run_subprocess_command(["git", "push", "-u", "origin", commit_branch_name])


def run_subprocess_command(command: list) -> None:
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        gha_utils.error(result.stderr)
        raise SystemExit(result.returncode)

    gha_utils.echo(result.stdout)
