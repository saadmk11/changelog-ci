import os
import subprocess
from typing import Literal

import requests


def print_message(
    message: str,
    message_type: Literal["warning", "error", "group", "endgroup"] | None = None,
) -> subprocess.CompletedProcess | None:
    """Helper function to print colorful outputs in GitHub Actions shell"""
    # https://docs.github.com/en/actions/reference/workflow-commands-for-github-actions
    if os.environ.get("PYTHON_TESTENV"):
        return None

    if not message_type:
        return subprocess.run(["echo", f"{message}"])

    if message_type == "endgroup":
        return subprocess.run(["echo", "::endgroup::"])

    return subprocess.run(["echo", f"::{message_type}::{message}"])


def display_whats_new() -> None:
    """function that prints what's new in Changelog CI Latest Version"""
    url = "https://api.github.com/repos/saadmk11/changelog-ci/releases/latest"
    response = requests.get(url)

    if response.status_code == 200:
        response_data = response.json()
        latest_release_tag = response_data["tag_name"]
        latest_release_html_url = response_data["html_url"]
        latest_release_body = response_data["body"]

        print_message(
            f"\U0001F389 What's New In Changelog CI {latest_release_tag} \U0001F389",
            message_type="group",
        )
        print_message(f"\n{latest_release_body}")
        print_message(
            f"Get More Information about '{latest_release_tag}' "
            f"Here: {latest_release_html_url}"
        )
        print_message(
            "\nTo use these features please upgrade to "
            f"version '{latest_release_tag}' if you haven't already."
        )
        print_message(
            "\nReport Bugs or Add Feature Requests Here: "
            "https://github.com/saadmk11/changelog-ci/issues"
        )

        print_message("", message_type="endgroup")
