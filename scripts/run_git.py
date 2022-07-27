import subprocess

import github_action_utils as gha_utils  # type: ignore


def checkout_pull_request_branch(branch_name: str) -> None:
    """
    Checkout the PR branch and pull the latest changes.
    """
    subprocess.run(["echo", f"::group:: Checkout '{branch_name}' branch"])
    subprocess.run(["git", "fetch", "--prune", "--unshallow", "origin", branch_name])
    subprocess.run(["git", "checkout", branch_name])
    subprocess.run(["echo", "::endgroup::"])


def configure_git_author(username: str, email: str) -> None:
    """
    Configure the git author.
    """
    subprocess.run(["git", "config", "user.name", username])
    subprocess.run(["git", "config", "user.email", email])


def create_new_git_branch(base_branch_name: str, new_branch_name: str) -> None:
    """
    Create a new git branch from base branch.
    """
    subprocess.run(
        [
            "echo",
            f"::group:: Create New Branch ({base_branch_name} -> {new_branch_name})",
        ]
    )
    subprocess.run(["git", "checkout", base_branch_name])
    subprocess.run(["git", "checkout", "-b", new_branch_name])
    subprocess.run(["echo", "::endgroup::"])


def git_commit_changelog(
    commit_message: str, changed_file: str, commit_author: str, commit_branch_name: str
) -> None:
    """
    Commit the changelog file.
    """
    subprocess.run(["echo", f"::group:: Commit Changelog ({changed_file})"])
    subprocess.run(["git", "add", changed_file])
    subprocess.run(["git", "commit", f"--author={commit_author}", "-m", commit_message])
    subprocess.run(["git", "push", "-u", "origin", commit_branch_name])
    subprocess.run(["echo", "::endgroup::"])
