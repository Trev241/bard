import asyncio
import logging

import discord

from bot.core.github_issues import GitHubIssueError, build_issue_body

logger = logging.getLogger(__name__)


class IssueReportView(discord.ui.View):
    def __init__(self, github_issues, context, error_text=None):
        super().__init__(timeout=300)
        self.github_issues = github_issues
        self.context = context
        self.error_text = error_text

    @discord.ui.button(label="Report issue", style=discord.ButtonStyle.primary)
    async def open_report_form(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(
            IssueReportModal(self.github_issues, self.context, self.error_text)
        )


class IssueReportModal(discord.ui.Modal, title="Report a Bard Issue"):
    summary = discord.ui.TextInput(
        label="Short summary",
        placeholder="Example: Bard stopped playing after one song",
        max_length=120,
    )
    description = discord.ui.TextInput(
        label="What happened?",
        style=discord.TextStyle.paragraph,
        max_length=1200,
    )
    expected = discord.ui.TextInput(
        label="What did you expect?",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800,
    )
    steps = discord.ui.TextInput(
        label="Steps or context",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Command used, song name, voice channel state, etc.",
        max_length=1000,
    )
    logs = discord.ui.TextInput(
        label="Error text or recent logs",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1500,
    )

    def __init__(self, github_issues, context, error_text=None):
        super().__init__()
        self.github_issues = github_issues
        self.context = context
        if error_text:
            self.logs.default = error_text[:1500]

    async def on_submit(self, interaction: discord.Interaction):
        report = {
            "summary": str(self.summary).strip(),
            "description": str(self.description).strip(),
            "expected": str(self.expected).strip(),
            "steps": str(self.steps).strip(),
            "logs": str(self.logs).strip(),
        }
        body = build_issue_body(report, self.context)

        try:
            issue = await asyncio.to_thread(
                self.github_issues.create_issue,
                f"Discord report: {report['summary']}",
                body,
            )
        except GitHubIssueError as exc:
            logger.warning("Failed to create GitHub issue from Discord report.", exc_info=True)
            await interaction.response.send_message(
                f"I could not create the GitHub issue: {exc}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Created GitHub issue: {issue.get('html_url', issue.get('url'))}",
            ephemeral=True,
        )

    async def on_error(self, interaction, error):
        logger.warning("Issue report modal failed.", exc_info=error)
        await interaction.response.send_message(
            "I could not submit that report. Check the bot logs for details.",
            ephemeral=True,
        )


def issue_context_from_message(message, referenced_message=None):
    referenced_url = None
    if referenced_message:
        referenced_url = referenced_message.jump_url
    elif message.reference and message.reference.resolved:
        referenced_url = message.reference.resolved.jump_url

    guild = message.guild
    channel = message.channel
    author = message.author
    return {
        "reporter": f"{author} ({author.id})",
        "guild": f"{guild.name} ({guild.id})" if guild else "Direct message",
        "channel": f"{channel} ({channel.id})",
        "command_url": message.jump_url,
        "referenced_url": referenced_url,
    }
