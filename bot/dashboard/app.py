import json
import logging
import hmac
import hashlib

from bot import client, app, config, socketio
from flask import render_template, request, jsonify, abort
from threading import Timer
from bot.cogs.music import Music
from bot.core.logging_service import recent_logs

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

    client_avatar = (
        client.user.avatar.url
        if client.user and client.user.avatar
        else "/static/placeholder_icon.png"
    )
    return {"client_avatar": client_avatar, "head_commit": head_commit}


@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    music: Music = client.get_cog("Music")

    client_dtls = {}
    if music and music.playback_manager:
        client_dtls["curr_song"] = music.service.now()
        client_dtls["queue"] = list(music.service.queue())
        client_dtls["playback_paused"] = music.is_playback_paused()

    if client_dtls.get("curr_song"):
        return render_template("dashboard.html", client_dtls=client_dtls)
    else:
        return render_template("banner.html")


@app.route("/dashboard/logs")
def logs_dashboard():
    lines = parse_lines_arg(default=300, maximum=2000)
    return render_template(
        "logs.html",
        log_lines=recent_logs(max_lines=lines),
        line_count=lines,
        log_file=config.LOG_FILE.name,
    )


@app.route("/dashboard/logs/data")
def logs_data():
    lines = parse_lines_arg(default=300, maximum=2000)
    return jsonify({"lines": recent_logs(max_lines=lines), "line_count": lines})


def parse_lines_arg(default, maximum):
    try:
        lines = int(request.args.get("lines", default))
    except (TypeError, ValueError):
        lines = default

    return max(1, min(lines, maximum))


@app.route("/update", methods=["POST"])
def update():
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature or not verify_signature(request.data, signature):
        abort(403)  # Forbidden if no signature is present or if it's invalid

    # Trigger process restart after a delay of 5 seconds by updating commit info
    payload = request.get_json()
    Timer(5.0, _save_commit, args=(payload,)).start()

    return jsonify({"status": "success"}), 200


def _save_commit(payload):
    if not payload or "head_commit" not in payload:
        logger.warning("Webhook payload did not include head_commit.")
        return

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
