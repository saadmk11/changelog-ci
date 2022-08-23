from functools import lru_cache

import github_action_utils as gha_utils  # type: ignore
import requests


@lru_cache
def get_request_headers(github_token: str | None = None) -> dict[str, str]:
    """Get headers for GitHub API request"""
    headers = {"Accept": "application/vnd.github.v3+json"}

    if github_token:
        headers.update({"authorization": f"Bearer {github_token}"})

    return headers


def display_whats_new() -> None:
    """function that prints what's new in Changelog CI Latest Version"""
    url = "https://api.github.com/repos/saadmk11/changelog-ci/releases/latest"
    response = requests.get(url)

    if response.status_code == 200:
        response_data = response.json()
        latest_release_tag = response_data["tag_name"]
        latest_release_html_url = response_data["html_url"]
        latest_release_body = response_data["body"]

        group_title = (
            f"\U0001F389 What's New In Changelog CI {latest_release_tag} \U0001F389"
        )

        with gha_utils.group(group_title):
            gha_utils.echo(latest_release_body)
            gha_utils.echo(
                f"Get More Information about '{latest_release_tag}' "
                f"Here: {latest_release_html_url}"
            )
            gha_utils.echo(
                "\nTo use these features please upgrade to "
                f"version '{latest_release_tag}' if you haven't already."
            )
            gha_utils.echo(
                "\nReport Bugs or Add Feature Requests Here: "
                "https://github.com/saadmk11/changelog-ci/issues"
            )
