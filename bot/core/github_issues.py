import requests

from bot import config


class GitHubIssueError(Exception):
    pass


class GitHubIssueClient:
    API_ROOT = "https://api.github.com"

    def __init__(self, repo=None, token=None, labels=None, session=None):
        self.repo = repo if repo is not None else config.GITHUB_REPO
        self.token = token if token is not None else config.GITHUB_TOKEN
        self.labels = labels if labels is not None else config.GITHUB_ISSUE_LABELS
        self.session = session or requests.Session()

    @property
    def configured(self):
        return bool(self.repo and self.token)

    def create_issue(self, title, body):
        if not self.configured:
            raise GitHubIssueError("GitHub issue reporting is not configured.")

        response = self.session.post(
            f"{self.API_ROOT}/repos/{self.repo}/issues",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": title,
                "body": body,
                "labels": self.labels,
            },
            timeout=15,
        )

        if response.status_code >= 400:
            raise GitHubIssueError(
                f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )

        return response.json()


def build_issue_body(report, context):
    context_lines = [
        f"- Reporter: {context.get('reporter')}",
        f"- Guild: {context.get('guild')}",
        f"- Channel: {context.get('channel')}",
        f"- Report command: {context.get('command_url')}",
    ]
    if context.get("referenced_url"):
        context_lines.append(f"- Referenced message: {context.get('referenced_url')}")

    return "\n".join(
        [
            "## What happened",
            report["description"],
            "",
            "## Expected behavior",
            report["expected"] or "_Not provided._",
            "",
            "## Steps or context",
            report["steps"] or "_Not provided._",
            "",
            "## Discord context",
            *context_lines,
            "",
            "## Recent logs or error text",
            f"```text\n{report['logs'] or 'Not provided.'}\n```",
        ]
    )
