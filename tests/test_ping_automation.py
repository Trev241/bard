from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from discord import MessageType

from bot.core.message_features import PingAutomation


def make_message(author_id, channel_id, mentions, created_at):
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id),
        channel=SimpleNamespace(id=channel_id),
        mentions=mentions,
        created_at=created_at,
        type=MessageType.default,
    )


@pytest.mark.asyncio
async def test_interleaved_channel_traffic_does_not_break_repeated_mentions():
    util = SimpleNamespace(is_pinging=False, ping_who={}, ping=AsyncMock())
    client = SimpleNamespace(
        get_cog=lambda name: util if name == "Utils" else None,
        get_context=AsyncMock(return_value=object()),
    )
    automation = PingAutomation(client)
    target = SimpleNamespace(id=99)
    start = datetime.now(timezone.utc)

    messages = [
        make_message(1, 10, [target], start),
        make_message(2, 20, [], start + timedelta(seconds=1)),
        make_message(1, 10, [target], start + timedelta(seconds=2)),
        make_message(2, 10, [], start + timedelta(seconds=3)),
        make_message(1, 10, [target], start + timedelta(seconds=4)),
    ]

    for message in messages:
        await automation.handle_message(message)

    util.ping.assert_awaited_once_with(messages[-1].channel, [target], 25)


@pytest.mark.asyncio
async def test_repeated_mentions_are_scoped_to_the_same_author():
    util = SimpleNamespace(is_pinging=False, ping_who={}, ping=AsyncMock())
    client = SimpleNamespace(
        get_cog=lambda name: util if name == "Utils" else None,
        get_context=AsyncMock(return_value=object()),
    )
    automation = PingAutomation(client)
    target = SimpleNamespace(id=99)
    start = datetime.now(timezone.utc)

    for offset, author_id in enumerate((1, 2, 1)):
        await automation.handle_message(
            make_message(author_id, 10, [target], start + timedelta(seconds=offset))
        )

    util.ping.assert_not_awaited()
