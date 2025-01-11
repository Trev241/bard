import sqlite3
import json
import discord
import re
import yt_dlp
import logging
import validators

from sqlite3 import IntegrityError
from datetime import datetime
from requests import get
from discord.ext import commands
from bot import logger
from bot.cogs.music import Music

logger = logging.getLogger(__name__)


class Analytics(commands.Cog):
    def __init__(self, client):
        self.client = client

        # Setting up SQLite
        self.conn = sqlite3.connect("bot/stats.db", check_same_thread=False)
        table = """
            CREATE TABLE IF NOT EXISTS tracks (
                message_id VARCHAR(255) PRIMARY KEY,
                channel_id VARCHAR(255) NOT NULL,
                guild_id VARCHAR(255) NOT NULL,
                title VARCHAR(255) NOT NULL,
                requester_id VARCHAR(255) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        self.cursor = self.conn.cursor()
        self.cursor.execute(table)

    def submit_track(
        self,
        message_id,
        channel_id,
        guild_id,
        title,
        requester_id,
        timestamp,
        commit=True,
    ):
        """Inserts a track into the database"""
        try:
            self.cursor.execute(
                """
                INSERT INTO tracks (message_id, channel_id, guild_id, title, requester_id, timestamp) 
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ((message_id, channel_id, guild_id, title, requester_id, timestamp)),
            )
            if commit:
                self.conn.commit()

        except IntegrityError as e:
            logger.warning(f"Failed to add track: {e}")

    def commit_db(self):
        """Commits any pending database transactions"""
        self.conn.commit()

    def latest_in_channel(self, channel_id):
        self.cursor.execute(
            """
            SELECT timestamp 
            FROM tracks 
            WHERE channel_id = (?) 
            ORDER BY timestamp DESC 
            LIMIT 1
            """,
            (str(channel_id),),
        )
        return self.cursor.fetchall()

    def get_tracks(self):
        self.cursor.execute("SELECT * FROM tracks")
        return self.cursor.fetchall()

    def get_tracks_by_freq(self, year, guild_id, most_frequent=True, limit=100):
        order = "DESC" if most_frequent else "ASC"
        self.cursor.execute(
            f"""
            SELECT title, timestamp, COUNT(*) AS count 
            FROM tracks 
            WHERE strftime('%Y', timestamp) = (?) AND guild_id = (?)
            GROUP BY title 
            ORDER BY count {order} LIMIT {limit}
            """,
            (year, guild_id),
        )
        return self.cursor.fetchall()

    def get_tracks_by_requester(self, requester_id, guild_id, year, limit=5):
        self.cursor.execute(
            f"""
            SELECT title, timestamp, COUNT(*) AS count 
            FROM tracks 
            WHERE 
                requester_id = (?) AND 
                strftime('%Y', timestamp) = (?) AND
                guild_id = (?)
            GROUP BY title 
            ORDER BY count DESC
            LIMIT {limit}
            """,
            (requester_id, year, guild_id),
        )
        return self.cursor.fetchall()

    def get_tracks_by_year(self, year):
        self.cursor.execute(
            """
            SELECT title, timestamp, COUNT(*) AS count 
            FROM tracks 
            WHERE strftime('%Y', timestamp) = (?)
            """,
            (year,),
        )
        return self.cursor.fetchall()

    def get_track_playcount(self):
        self.cursor.execute(
            """
            SELECT title, COUNT(*) AS count 
            FROM tracks 
            GROUP BY title 
            ORDER BY count DESC
            """
        )
        return self.cursor.fetchall()

    def get_top_requesters(self, guild_id, year):
        self.cursor.execute(
            f"""
            SELECT requester_id, COUNT(*) as count, timestamp 
            FROM tracks
            WHERE 
                guild_id = (?) AND 
                strftime('%Y', timestamp) = (?)
            GROUP BY requester_id 
            ORDER BY count DESC
            """,
            (guild_id, year),
        )
        return self.cursor.fetchall()

    def get_years(self):
        self.cursor.execute(
            """
            SELECT DISTINCT strftime('%Y', timestamp) AS y
            FROM tracks
            """
        )
        return self.cursor.fetchall()

    def get_guilds(self):
        self.cursor.execute(
            """
            SELECT DISTINCT guild_id
            FROM tracks
            """
        )
        guild_ids = self.cursor.fetchall()
        guilds = [self.client.get_guild(int(guild_id[0])) for guild_id in guild_ids]

        logger.info(f"Returning guild info: {guilds}")
        return guilds

    @commands.command()
    async def analyze(self, ctx, complete: bool = False):
        """
        Analyzes the current text channel in which the command was issued and
        updates the track database
        """

        PLAY_COMMAND_REGEX = r"^([^\s]+)play\s(.*)"
        message = await ctx.send(
            f"I'm going to check {ctx.channel.name} to update my records. This will take some time..."
        )
        record = self.latest_in_channel(ctx.channel.id)
        if len(record) > 0 and not complete:
            after = datetime.fromisoformat(record[0][0])
            logger.info(f"Only scanning for messages after {after}")
            messages = ctx.channel.history(limit=None, oldest_first=True, after=after)
        else:
            logger.info("Scanning the entire channel")
            messages = ctx.channel.history(limit=None, oldest_first=True)
        count = 0

        # Scan all messages
        async for message in messages:
            match = re.search(PLAY_COMMAND_REGEX, message.content)
            if match is None:
                print("No music command. Skipping...")
                continue

            query = match.group(2)
            ydl = yt_dlp.YoutubeDL(Music.YDL_OPTIONS)

            # Determine if query is a link or not
            is_link = validators.url(query)

            # Attempt to retrieve information about the query
            try:
                if is_link:
                    info = ydl.extract_info(query, download=False, process=False)
                else:
                    info = ydl.extract_info(
                        f"ytsearch:{query}", download=False, process=False
                    )
            except Exception as e:
                logger.warning(
                    f"An error occurred while trying to qualify the query '{query}': {e}"
                )

            try:
                if not (info.get("_type", None) == "playlist"):
                    info["entries"] = [info]

                for entry in info["entries"]:
                    entry["requester"] = ctx.author
                    self.submit_track(
                        message.id,
                        message.channel.id,
                        message.guild.id,
                        entry["title"],
                        message.author.id,
                        message.created_at,
                        commit=False,
                    )
                    count += 1
                    logger.info(f"Saved entry for track {entry['title']}")
            except Exception as e:
                logger.warning(
                    f"An error occurred while trying to qualifying the query '{query}': {e}"
                )

        self.commit_db()
        await ctx.send(
            f"Scan for text channel {ctx.channel.name} complete. Updated {count} record(s)"
        )

    @commands.command()
    async def analytics(self, ctx):
        analytics_data = self.get_tracks()
        with open("bot/stats.json", "w") as fp:
            json.dump(analytics_data, fp, indent=2)
        with open("bot/stats.json") as fp:
            await ctx.send(file=discord.File(fp))


async def setup(client):
    await client.add_cog(Analytics(client))
