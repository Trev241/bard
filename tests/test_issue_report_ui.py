from types import SimpleNamespace

from bot.core.issue_report_ui import issue_context_from_message


class FakeNamedObject:
    def __init__(self, value, id):
        self.value = value
        self.id = id

    def __str__(self):
        return self.value


def test_issue_context_uses_referenced_message_when_provided():
    message = SimpleNamespace(
        author=FakeNamedObject("Reporter", 1),
        guild=SimpleNamespace(id=2, name="Guild"),
        channel=FakeNamedObject("general", 3),
        jump_url="https://discord.test/command",
        reference=None,
    )
    referenced = SimpleNamespace(jump_url="https://discord.test/error")

    context = issue_context_from_message(message, referenced_message=referenced)

    assert context["referenced_url"] == "https://discord.test/error"
    assert context["command_url"] == "https://discord.test/command"
