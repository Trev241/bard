import pytest
import json

from bot.cogs.music import Music, MusicRequest
from bot.models import Source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["bard - lonely", "https://www.youtube.com/watch?v=EyIBUR5LCpw"],
)
@pytest.mark.parametrize(
    "source",
    [Source.CMD, Source.WEB],
)
async def test_play_positive(query, source, mocker):
    mock_cog = mocker.Mock(submit_track=None)
    mock_client = mocker.Mock(get_cog=mock_cog)
    mock_author = mocker.Mock(id=987)
    mock_msg = mocker.Mock()
    mock_msg.id = 123
    mock_msg.channel.id = 456
    mock_msg.guild.id = 789
    mock_ctx = mocker.AsyncMock()
    mock_ctx.send.return_value = mock_msg
    mock_ctx.voice_client = mocker.Mock(play="None")

    # import yt_dlp.YoutubeDL

    # with open("tests/yt-dlp.json") as fp:
    #     api_data = json.load(fp)
    # mock_ydl = mocker.patch("yt_dlp.YoutubeDL")
    # mock_ydl.process_ie_result.return_value = api_data

    music_cog = Music(mock_client)
    await music_cog.play(MusicRequest(query, mock_author, mock_ctx, source))

    assert len(music_cog.queue) == 1
