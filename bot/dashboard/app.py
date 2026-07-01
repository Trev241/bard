import json
import logging
import hmac
import hashlib

from bot import client, app, config, socketio
from flask import render_template, request, jsonify, abort
from threading import Timer
from bot.cogs.music import Music
from bot.core.env_file import read_env_values, update_env_file
from bot.core.logging_service import recent_logs
from bot.core.writing_feedback import GeminiWritingRewriteProvider

logger = logging.getLogger(__name__)
ENV_PATH = config.PROJECT_ROOT / ".env"
DEFAULT_TRANSLATION_DASHBOARD_SETTINGS = {
    "TRANSLATION_PROVIDER": "argos",
    "TRANSLATION_PROVIDER_BY_DIRECTION": None,
    "TRANSLATION_CHANNEL_PAIRS": "",
    "WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD": "25",
    "WRITING_FEEDBACK_AUTO_REPLY": "false",
    "WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS": None,
    "WRITING_FEEDBACK_LLM_PROMPT": None,
}


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


@app.route("/dashboard/translation", methods=["GET", "POST"])
def translation_settings_dashboard():
    status = None
    errors = []

    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "reset":
            update_env_file(ENV_PATH, DEFAULT_TRANSLATION_DASHBOARD_SETTINGS)
            apply_translation_dashboard_config(DEFAULT_TRANSLATION_DASHBOARD_SETTINGS)
            status = "reset"
        else:
            updates, errors = translation_settings_updates_from_form(request.form)
            if not errors:
                update_env_file(ENV_PATH, updates)
                apply_translation_dashboard_config(updates)
                status = "saved"

    settings = current_translation_dashboard_settings()
    return render_template(
        "translation_settings.html",
        settings=settings,
        default_prompt=GeminiWritingRewriteProvider.DEFAULT_SYSTEM_PROMPT,
        status=status,
        errors=errors,
    )


def parse_lines_arg(default, maximum):
    try:
        lines = int(request.args.get("lines", default))
    except (TypeError, ValueError):
        lines = default

    return max(1, min(lines, maximum))


def current_translation_dashboard_settings():
    values = read_env_values(ENV_PATH)
    pair = first_translation_pair(values.get("TRANSLATION_CHANNEL_PAIRS"))
    source_lang = pair.get("source_lang") or "en"
    mirror_lang = pair.get("mirror_lang") or "fr"
    providers_by_direction = provider_by_direction_from_values(values)

    return {
        "source_channel_id": str(pair.get("source_channel_id") or ""),
        "mirror_channel_id": str(pair.get("mirror_channel_id") or ""),
        "source_lang": source_lang,
        "mirror_lang": mirror_lang,
        "translation_provider": values.get(
            "TRANSLATION_PROVIDER", config.TRANSLATION_PROVIDER
        ).strip().casefold()
        or "argos",
        "source_to_mirror_provider": providers_by_direction.get(
            (source_lang.casefold(), mirror_lang.casefold()),
            values.get("TRANSLATION_PROVIDER", config.TRANSLATION_PROVIDER),
        ).strip().casefold()
        or "argos",
        "mirror_to_source_provider": providers_by_direction.get(
            (mirror_lang.casefold(), source_lang.casefold()),
            values.get("TRANSLATION_PROVIDER", config.TRANSLATION_PROVIDER),
        ).strip().casefold()
        or "argos",
        "auto_rewrite_threshold": values.get(
            "WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD",
            str(config.WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD),
        ),
        "auto_rewrite_enabled": parse_bool_value(
            values.get(
                "WRITING_FEEDBACK_AUTO_REPLY",
                str(config.WRITING_FEEDBACK_AUTO_REPLY),
            )
        ),
        "llm_extra_instructions": values.get(
            "WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS",
            config.WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS,
        ),
    }


def first_translation_pair(raw_pairs=None):
    try:
        pairs = config.parse_translation_channel_pairs(raw_pairs or "")
    except (TypeError, ValueError):
        pairs = []

    if pairs:
        return pairs[0]

    return {
        "source_channel_id": "",
        "mirror_channel_id": "",
        "source_lang": "en",
        "mirror_lang": "fr",
    }


def translation_settings_updates_from_form(form):
    errors = []
    source_channel_id = (form.get("source_channel_id") or "").strip()
    mirror_channel_id = (form.get("mirror_channel_id") or "").strip()
    source_lang = (form.get("source_lang") or "en").strip().casefold() or "en"
    mirror_lang = (form.get("mirror_lang") or "fr").strip().casefold() or "fr"
    source_to_mirror_provider = (
        form.get("source_to_mirror_provider") or "argos"
    ).strip().casefold()
    mirror_to_source_provider = (
        form.get("mirror_to_source_provider") or "argos"
    ).strip().casefold()
    threshold = (form.get("auto_rewrite_threshold") or "").strip()
    extra_instructions = (form.get("llm_extra_instructions") or "").strip()

    for label, provider in (
        ("Source to mirror translation service", source_to_mirror_provider),
        ("Mirror to source translation service", mirror_to_source_provider),
    ):
        if provider not in {"argos", "gemini"}:
            errors.append(f"{label} must be Argos or Gemini.")

    if bool(source_channel_id) != bool(mirror_channel_id):
        errors.append("Both channel IDs are required when configuring a pair.")

    for label, value in (
        ("Source channel ID", source_channel_id),
        ("Mirror channel ID", mirror_channel_id),
    ):
        if value and not value.isdigit():
            errors.append(f"{label} must contain digits only.")

    try:
        threshold_int = int(threshold)
    except ValueError:
        errors.append("LLM rewrite score threshold must be a number from 0 to 100.")
        threshold_int = 25
    else:
        if not 0 <= threshold_int <= 100:
            errors.append("LLM rewrite score threshold must be from 0 to 100.")

    channel_pairs = ""
    if source_channel_id and mirror_channel_id:
        channel_pairs = (
            f"{source_channel_id}:{mirror_channel_id}:{source_lang}:{mirror_lang}"
        )

    provider_by_direction = (
        f"{source_lang}->{mirror_lang}:{source_to_mirror_provider},"
        f"{mirror_lang}->{source_lang}:{mirror_to_source_provider}"
    )

    return (
        {
            "TRANSLATION_PROVIDER": source_to_mirror_provider,
            "TRANSLATION_PROVIDER_BY_DIRECTION": provider_by_direction,
            "TRANSLATION_CHANNEL_PAIRS": channel_pairs,
            "WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD": str(threshold_int),
            "WRITING_FEEDBACK_AUTO_REPLY": (
                "true" if form.get("auto_rewrite_enabled") else "false"
            ),
            "WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS": extra_instructions or None,
            "WRITING_FEEDBACK_LLM_PROMPT": None,
        },
        errors,
    )


def apply_translation_dashboard_config(updates):
    for key, value in updates.items():
        if value is None:
            value = ""
        if key == "TRANSLATION_PROVIDER":
            config.TRANSLATION_PROVIDER = value.strip().casefold()
        elif key == "TRANSLATION_PROVIDER_BY_DIRECTION":
            config.TRANSLATION_PROVIDER_BY_DIRECTION = value
        elif key == "TRANSLATION_CHANNEL_PAIRS":
            config.TRANSLATION_CHANNEL_PAIRS = value
        elif key == "WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD":
            config.WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD = int(value or 25)
        elif key == "WRITING_FEEDBACK_AUTO_REPLY":
            config.WRITING_FEEDBACK_AUTO_REPLY = parse_bool_value(value)
        elif key == "WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS":
            config.WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS = (
                value.replace("\\n", "\n").strip()
            )


def provider_by_direction_from_values(values):
    raw_value = values.get(
        "TRANSLATION_PROVIDER_BY_DIRECTION",
        config.TRANSLATION_PROVIDER_BY_DIRECTION,
    )
    try:
        return config.parse_translation_provider_by_direction(raw_value)
    except ValueError:
        logger.warning("Invalid TRANSLATION_PROVIDER_BY_DIRECTION in .env.")
        return {}


def parse_bool_value(value):
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


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
