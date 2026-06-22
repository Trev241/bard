import json
import logging
import hmac
import hashlib
import random
import asyncio

import yt_dlp

from bot import client, app, config, socketio
from flask import render_template, request, jsonify, abort
from threading import Timer
from bot.cogs.music import Music
from bot.core.youtube import create_ytdlp

logger = logging.getLogger(__name__)


@app.context_processor
def inject_client_info():
    head_commit = {}
    try:
        fp = open(config.HEAD_COMMIT_DUMP)
    except FileNotFoundError:
        logger.warning("Failed to open head-commit.json")
    else:
        with fp:
            head_commit = json.load(fp)

    client_avatar = client.user.avatar.url
    return {"client_avatar": client_avatar, "head_commit": head_commit}


@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    music: Music = client.get_cog("Music")

    client_dtls = {}
    if music.playback_manager:
        client_dtls["curr_song"] = music.playback_manager.curr_song
        client_dtls["queue"] = list(music.playback_manager.queue)
        client_dtls["playback_paused"] = music.is_playback_paused()

    if client_dtls.get("curr_song"):
        return render_template("dashboard.html", client_dtls=client_dtls)
    else:
        return render_template("banner.html")


@app.route("/update", methods=["POST"])
def update():
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature or not verify_signature(request.data, signature):
        abort(403)  # Forbidden if no signature is present or if it's invalid

    # Trigger process restart after a delay of 5 seconds by updating commit info
    payload = request.get_json()
    Timer(5.0, _save_commit, args=(payload,)).start()

    return jsonify({"status": "success"}), 200


@app.route("/analytics")
def analytics():
    # http://localhost:5000/analytics?year=2024&guild_id=423759031157653504
    analytics_base = client.get_cog("Analytics")

    if "year" in request.args and "guild_id" in request.args:
        year = request.args.get("year")
        guild_id = request.args.get("guild_id")
        guild = get_guild_dtls(guild_id)

        top_tracks = analytics_base.get_tracks_by_freq(year, guild_id, limit=5)
        bot_tracks = analytics_base.get_tracks_by_freq(year, guild_id, False)

        prcsd_top_tracks = []
        for track in top_tracks:
            prcsd_top_tracks.append(
                {
                    "title": track[0],
                    "count": track[2],
                    "info": get_track_dtls(track[0]),
                }
            )
        prcsd_bot_tracks = []
        for track in random.sample(bot_tracks, min(len(bot_tracks), 5)):
            prcsd_bot_tracks.append(
                {
                    "title": track[0],
                    "count": track[2],
                    "info": get_track_dtls(track[0]),
                }
            )

        usr_tracks = {}
        usr_dtls = {}

        top_usrs = analytics_base.get_top_requesters(guild_id, year)
        for usr in top_usrs:
            usr_id = usr[0]
            tracks = analytics_base.get_tracks_by_requester(usr_id, guild_id, year)

            usr_tracks[usr_id] = [
                {
                    "title": track[0],
                    "count": track[2],
                    "info": get_track_dtls(track[0]),
                }
                for track in tracks
            ]

            # full_usr_dtls = get_usr_dtls(usr_id)
            logger.info(usr_id)
            full_usr_dtls = get_usr_dtls(int(usr_id))
            usr_dtls[usr_id] = {
                "name": full_usr_dtls.display_name if full_usr_dtls else f"User {usr_id}",
                "avatar": full_usr_dtls.display_avatar.url if full_usr_dtls else None,
                "requests": usr[1],
            }

        data = {
            "top_tracks": prcsd_top_tracks,
            "bot_tracks": prcsd_bot_tracks,
            "usr_tracks": usr_tracks,
            "all_tracks": analytics_base.get_tracks_by_freq(year, guild_id, limit=-1),
            "usr_dtls": usr_dtls,
            "year": request.args.get("year"),
            "guild": {
                "name": guild.name if guild else f"Guild {guild_id}",
                "icon": guild.icon.url if guild and guild.icon else None,
            },
        }
        return render_template("analytics.html", data=data)
    else:
        data = {
            "years": analytics_base.get_years(),
            "guilds": analytics_base.get_guilds(),
        }
        return render_template("analytics_home.html", data=data)


def get_track_dtls(title):
    """Return track details"""
    ydl = create_ytdlp(flat=True)
    info = ydl.extract_info(f"ytsearch1:{title}", download=False, process=False)
    info["entries"] = list(info.get("entries", []))
    # We assume we need only the first entry
    extracted_info = yt_dlp.traverse_obj(
        info,
        ["entries", ..., {"title": "title", "thumbnails": "thumbnails"}],
    )

    return extracted_info[0] if len(extracted_info) > 0 else None


def get_guild_dtls(guild_id):
    """Return guild details synchronously"""
    coro = client.fetch_guild(int(guild_id))
    fut = asyncio.run_coroutine_threadsafe(coro, client.loop)
    try:
        return fut.result()
    except Exception:
        logger.warning("Failed to fetch guild %s.", guild_id, exc_info=True)

    return None


def get_usr_dtls(user_id):
    """Return user details"""
    coro = client.fetch_user(int(user_id))
    fut = asyncio.run_coroutine_threadsafe(coro, client.loop)
    try:
        return fut.result()
    except Exception:
        logger.warning("Failed to fetch user %s.", user_id, exc_info=True)

    return None


def _save_commit(payload):
    with open(config.HEAD_COMMIT_DUMP, "w") as fp:
        json.dump(payload["head_commit"], fp)
    logger.info("Successfully saved head commit.")


def verify_signature(payload_body, signature):
    if not config.WEBHOOK_SECRET:
        logger.warning("Rejecting webhook because WEBHOOK_SECRET is not configured.")
        return False

    mac = hmac.new(config.WEBHOOK_SECRET.encode(), payload_body, hashlib.sha256)
    expected_signature = "sha256=" + mac.hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def run_flask(debug=True):
    socketio.run(app, use_reloader=False, debug=debug, allow_unsafe_werkzeug=True)
