import asyncio
import logging
import threading

from discord.ext import tasks
import discord

from bot import client, config, log_handlers, log_formatter, public_url, socketio
from bot.dashboard.app import run_flask
from bot.cogs.music import Music
import bot.cogs.music as music
import bot.cogs.utils as utils
import bot.cogs.events as events
import bot.cogs.wordle as wordle
import bot.cogs.analytics as analytics

# import bot.cogs.assistant as assistant


logger = logging.getLogger(__name__)

# ADDING COGS TO BOT
# Assistant temporarily removed
cogs = [music, utils, events, wordle, analytics]


async def load_extensions():
    """Load all extensions asynchronously by inovking the setup method of each cog."""

    for i in range(len(cogs)):
        await cogs[i].setup(client)


@tasks.loop(seconds=1)
async def check_restart_signal():
    signal_file = config.RESTART_SIGNAL_FILE
    music_cog: Music = client.get_cog("Music")

    def remove_signal_file():
        try:
            signal_file.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove restart signal file.", exc_info=True)

    # Remove the signal file if it was not successfully removed after last reboot
    remove_signal_file()

    while True:
        if signal_file.exists():
            remove_signal_file()

            # Send an alert message
            if music_cog and music_cog.voice_client and music_cog.ctx:
                message = "I am scheduled to restart soon."
                if public_url:
                    message += f" [Learn more]({public_url}/maintenance)."
                await music_cog.ctx.send(message)

        await asyncio.sleep(1)


async def main():
    discord.utils.setup_logging(
        handler=log_handlers["strm"],
        formatter=log_formatter,
        level=logging.INFO,
        root=True,
    )

    async with client:
        await load_extensions()

        @client.listen()
        async def on_ready():
            check_restart_signal.start()

        logger.info(f"Socket IO async-mode: {socketio.async_mode}")
        if not config.TOKEN:
            raise RuntimeError("Missing Discord token. Set TOKEN in .env or the environment.")

        await client.start(token=config.TOKEN)


def start():
    asyncio.run(main())


if __name__ == "__main__":
    # Create worker thread for the bot application
    threading.Thread(target=start, daemon=True).start()
    run_flask()
