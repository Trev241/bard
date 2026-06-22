import pytest

from bot.core.github_issues import GitHubIssueClient, GitHubIssueError, build_issue_body


class FakeResponse:
    def __init__(self, status_code=201, payload=None, text=""):
        self.status_code = status_code
        self.payload = payload or {"html_url": "https://github.test/issue/1"}
        self.text = text

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def test_github_issue_client_creates_issue_payload():
    session = FakeSession(FakeResponse())
    client = GitHubIssueClient(
        repo="owner/repo",
        token="token",
        labels=["bug", "user-report"],
        session=session,
    )

    issue = client.create_issue("Title", "Body")

    assert issue["html_url"] == "https://github.test/issue/1"
    args, kwargs = session.calls[0]
    assert args[0] == "https://api.github.com/repos/owner/repo/issues"
    assert kwargs["json"] == {
        "title": "Title",
        "body": "Body",
        "labels": ["bug", "user-report"],
    }
    assert kwargs["headers"]["Authorization"] == "Bearer token"


def test_github_issue_client_requires_configuration():
    client = GitHubIssueClient(repo="", token="")

    with pytest.raises(GitHubIssueError):
        client.create_issue("Title", "Body")


def test_build_issue_body_includes_report_and_discord_context():
    body = build_issue_body(
        {
            "description": "Playback stopped.",
            "expected": "Continue playing.",
            "steps": "?play test",
            "logs": "Traceback...",
        },
        {
            "reporter": "User#0001 (1)",
            "guild": "Server (2)",
            "channel": "music (3)",
            "command_url": "https://discord.test/message",
            "referenced_url": "https://discord.test/error",
        },
    )

    assert "Playback stopped." in body
    assert "Continue playing." in body
    assert "Referenced message: https://discord.test/error" in body
    assert "Traceback..." in body
