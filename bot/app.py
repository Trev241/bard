import json
import logging

from bot import client, app, socketio
from flask import render_template, request

logger = logging.getLogger(__name__)


@app.route("/")
@app.route("/index")
def index():
    music = client.get_cog("Music")
    client_dtls = {
        "current_track": music.current_track,
        "queue": list(music.queue),
        "playback_paused": music.is_playback_paused(),
        "voice_channel": music.voice_channel,
    }

    return render_template("index.html", client_dtls=client_dtls)


@app.route("/update", methods=["POST"])
def update():
    payload = request.get_json()
    logger.info(f"Received payload from webhook: {json.dumps(payload)}")


def run_flask(debug=True):
    socketio.run(app, use_reloader=False, debug=debug)
