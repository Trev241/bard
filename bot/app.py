import json
import logging
import hmac
import hashlib
import os

from bot import client, app, socketio, restart_event
from flask import render_template, request, jsonify, abort
from dotenv import load_dotenv
from threading import Timer

logger = logging.getLogger(__name__)

load_dotenv()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")


@app.route("/")
@app.route("/index")
def index():
    with open("bot/head-commit.json") as fp:
        head_commit = json.load(fp)
    music = client.get_cog("Music")
    client_dtls = {
        "current_track": music.current_track,
        "queue": list(music.queue),
        "playback_paused": music.is_playback_paused(),
        "voice_channel": music.voice_channel,
    }

    return render_template(
        "index.html", client_dtls=client_dtls, head_commit=head_commit
    )


@app.route("/update", methods=["POST"])
def update():
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature or not verify_signature(request.data, signature):
        abort(403)  # Forbidden if no signature is present or if it's invalid

    payload = request.get_json()
    logger.info(f"Received payload from webhook: {json.dumps(payload)}")
    with open("bot/head-commit.json", "w") as fp:
        json.dump(payload["head_commit"], fp)

    # Restart the app
    Timer(3.0, lambda: restart_event.set()).start()
    logger.info("Shutting down...")
    # sys.exit(0)
    os._exit(0)
    logger.info("Exit command issued internally in Flask.")

    return jsonify({"status": "success"}), 200


def verify_signature(payload_body, signature):
    mac = hmac.new(WEBHOOK_SECRET.encode(), payload_body, hashlib.sha256)
    expected_signature = "sha256=" + mac.hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def run_flask(debug=True):
    socketio.run(app, use_reloader=False, debug=debug)
