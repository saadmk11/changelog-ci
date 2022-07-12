import subprocess


def checkout_pull_request_branch(branch_name: str) -> None:
    """
    Checkout the PR branch and pull the latest changes.
    """
    subprocess.run(['git', 'checkout', '-b', branch_name ])
    subprocess.run(['git', 'pull', 'origin', branch_name ])
