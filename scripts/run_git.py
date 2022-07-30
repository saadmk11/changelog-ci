import subprocess

import github_action_utils as gha_utils  # type: ignore


def checkout_pull_request_branch(branch_name: str) -> None:
    """
    Checkout the PR branch and pull the latest changes.
    """
    with gha_utils.group(f"\nCheckout '{branch_name}' branch", use_subprocess=True):
        subprocess.run(
            ["git", "fetch", "--prune", "--unshallow", "origin", branch_name]
        )
        subprocess.run(["git", "checkout", branch_name])


def configure_git_author(username: str, email: str) -> None:
    """
    Configure the git author.
    """
    with gha_utils.group("\nConfigure Git Author", use_subprocess=True):
        gha_utils.notice(f"Setting Git Commit User to '{username}'.", use_subprocess=True)
        gha_utils.notice(f"Setting Git Commit email to '{email}'.", use_subprocess=True)

        subprocess.run(["git", "config", "user.name", username])
        subprocess.run(["git", "config", "user.email", email])


def create_new_git_branch(base_branch_name: str, new_branch_name: str) -> None:
    """
    Create a new git branch from base branch.
    """
    with gha_utils.group(
        f"\nCreate New Branch ({base_branch_name} -> {new_branch_name})",
        use_subprocess=True,
    ):
        subprocess.run(["git", "checkout", base_branch_name])
        subprocess.run(["git", "checkout", "-b", new_branch_name])


def git_commit_changelog(
    commit_message: str, changed_file: str, commit_author: str, commit_branch_name: str
) -> None:
    """
    Commit the changelog file.
    """
    with gha_utils.group(f"\nCommit Changelog ({changed_file})", use_subprocess=True):
        subprocess.run(["git", "add", changed_file])
        subprocess.run(
            ["git", "commit", f"--author={commit_author}", "-m", commit_message]
        )
        subprocess.run(["git", "push", "-u", "origin", commit_branch_name])
