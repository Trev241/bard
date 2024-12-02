import sqlite3
import json
import discord

from discord.ext import commands


class Analytics(commands.Cog):
    def __init__(self, client):
        self.client = client

        # Setting up SQLite
        self.conn = sqlite3.connect("stats.db", check_same_thread=False)
        table = """
            CREATE TABLE IF NOT EXISTS tracks (
                title VARCHAR(255) NOT NULL, 
                requester_id VARCHAR(255) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        self.cursor = self.conn.cursor()
        self.cursor.execute(table)

    def submit_track(self, title, requester_id):
        self.cursor.execute(
            f"INSERT INTO tracks (title, requester_id) VALUES (?, ?)",
            ((title, requester_id)),
        )
        self.conn.commit()

    def get_tracks(self):
        self.cursor.execute("SELECT * FROM tracks")
        return self.cursor.fetchall()

    def get_track_playcount(self):
        self.cursor.execute(
            "SELECT title, COUNT(*) AS count FROM tracks GROUP BY title ORDER BY count DESC"
        )
        return self.cursor.fetchall()

    def get_top_requesters(self):
        self.cursor.execute(
            "SELECT requester_id, COUNT(*) as count FROM tracks GROUP BY requester_id ORDER BY count DESC"
        )
        return self.cursor.fetchall()

    @commands.command()
    async def analytics(self, ctx):
        analytics_data = self.get_tracks()
        with open("bot/stats.json", "w") as fp:
            json.dump(analytics_data, fp, indent=2)
        with open("bot/stats.json") as fp:
            await ctx.send(file=discord.File(fp))


async def setup(client):
    await client.add_cog(Analytics(client))
