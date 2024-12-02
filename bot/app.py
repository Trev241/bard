import json
import logging
import hmac
import hashlib
import os

from bot import client, app, socketio
from flask import render_template, request, jsonify, abort
from dotenv import load_dotenv
from threading import Timer
from bot.cogs.music import Music

logger = logging.getLogger(__name__)

load_dotenv()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")


@app.context_processor
def inject_client_info():
    with open("bot/head-commit.json") as fp:
        head_commit = json.load(fp)

    client_avatar = client.user.avatar.url
    return {"client_avatar": client_avatar, "head_commit": head_commit}


@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    music = client.get_cog("Music")

    client_dtls = {
        "current_track": music.current_track,
        "queue": Music.simplify_queue(music.queue),
        "playback_paused": music.is_playback_paused(),
        "voice_channel": music.voice_channel,
    }

    if client_dtls["current_track"]:
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
    analytics_base = client.get_cog("Analytics")
    data = analytics_base.get_track_playcount()
    top_players = analytics_base.get_top_requesters()
    if len(top_players) > 0:
        print(top_players[0][0])
        player = client.get_user(int(top_players[0][0]))
        top_players = {"display_name": player.display_name, "avatar": player.avatar.url}
    else:
        top_players = "No one yet..."

    return render_template("analytics.html", data=data, top_players=top_players)


def _save_commit(payload):
    with open("bot/head-commit.json", "w") as fp:
        json.dump(payload["head_commit"], fp)
    logger.info("Successfully saved head commit.")


def verify_signature(payload_body, signature):
    mac = hmac.new(WEBHOOK_SECRET.encode(), payload_body, hashlib.sha256)
    expected_signature = "sha256=" + mac.hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def run_flask(debug=True):
    socketio.run(app, use_reloader=False, debug=debug)
