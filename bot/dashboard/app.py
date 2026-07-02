import json
import logging
import hmac
import hashlib
import secrets
import asyncio
from urllib.parse import urlencode

from bot import client, app, config, socketio
from flask import (
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from threading import Timer
import requests

from bot.cogs.music import Music
from bot.core.logging_service import recent_logs
from bot.core.translation_settings import (
    GuildTranslationSettings,
    TranslationSettingsStore,
    direction_key,
)
from bot.core.writing_feedback import GeminiWritingRewriteProvider

logger = logging.getLogger(__name__)
DISCORD_API_BASE_URL = "https://discord.com/api/v10"
DISCORD_OAUTH_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_OAUTH_TOKEN_URL = f"{DISCORD_API_BASE_URL}/oauth2/token"
DISCORD_ADMINISTRATOR_PERMISSION = 0x8
TRANSLATION_SETTINGS_STORE = TranslationSettingsStore(
    config.TRANSLATION_GUILD_SETTINGS_FILE
)


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
    return {"client_avatar": client_avatar, "head_commit": head_commit, "config": config}


@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")


@app.before_request
def require_dashboard_auth():
    g.dashboard_user = session.get("discord_user")
    if not config.DASHBOARD_AUTH_ENABLED:
        return None

    path = request.path.rstrip("/")
    if not path.startswith("/dashboard"):
        return None
    if path.startswith("/dashboard/auth"):
        return None

    if not dashboard_oauth_configured():
        return render_template("dashboard_auth_setup.html"), 503

    if not session.get("discord_user"):
        return redirect(url_for("dashboard_login", next=request.full_path))

    return None


@app.route("/dashboard/auth/login")
def dashboard_login():
    if not dashboard_oauth_configured():
        return render_template("dashboard_auth_setup.html"), 503

    state = secrets.token_urlsafe(24)
    session["dashboard_oauth_state"] = state
    next_url = request.args.get("next") or url_for("dashboard")
    session["dashboard_auth_next"] = next_url
    params = {
        "client_id": config.DASHBOARD_DISCORD_CLIENT_ID,
        "redirect_uri": config.DASHBOARD_DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
    }
    return redirect(f"{DISCORD_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.route("/dashboard/auth/callback")
def dashboard_auth_callback():
    if request.args.get("state") != session.pop("dashboard_oauth_state", None):
        abort(403)

    code = request.args.get("code")
    if not code:
        abort(400)

    token = exchange_discord_oauth_code(code)
    user = discord_api_get("/users/@me", token["access_token"])
    guilds = discord_api_get("/users/@me/guilds", token["access_token"])
    session["discord_user"] = {
        "id": int(user["id"]),
        "username": user.get("global_name") or user.get("username") or "Discord user",
        "avatar": user.get("avatar"),
    }
    session["discord_guilds"] = guilds

    next_url = session.pop("dashboard_auth_next", None) or url_for("dashboard")
    return redirect(next_url)


@app.route("/dashboard/auth/logout")
def dashboard_logout():
    session.pop("discord_user", None)
    session.pop("discord_guilds", None)
    session.pop("dashboard_oauth_state", None)
    return redirect(url_for("index"))


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
    guilds = authorized_dashboard_guilds()
    selected_guild_id = selected_dashboard_guild_id(guilds)
    selected_guild = guild_by_id(selected_guild_id)

    if request.method == "POST":
        selected_guild_id = selected_dashboard_guild_id(guilds, request.form)
        selected_guild = guild_by_id(selected_guild_id)
        if selected_guild is None:
            errors.append("Choose a guild before changing translation settings.")

        action = request.form.get("action", "save")
        if action == "reset" and selected_guild is not None:
            TRANSLATION_SETTINGS_STORE.save(
                GuildTranslationSettings(guild_id=selected_guild.id)
            )
            schedule_translation_settings_reload()
            status = "reset"
        elif selected_guild is not None:
            setting, form_errors = translation_settings_from_form(
                selected_guild,
                request.form,
            )
            errors.extend(form_errors)
            if not errors:
                TRANSLATION_SETTINGS_STORE.save(setting)
                schedule_translation_settings_reload()
                status = "saved"

    settings = current_translation_dashboard_settings(selected_guild)
    return render_template(
        "translation_settings.html",
        guilds=guilds,
        selected_guild=selected_guild,
        channels=text_channels_for_guild(selected_guild),
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


def current_translation_dashboard_settings(guild):
    if guild is None:
        return GuildTranslationSettings(guild_id=0)

    return TRANSLATION_SETTINGS_STORE.get(guild.id)


def translation_settings_from_form(guild, form):
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

    channel_ids = {str(channel.id) for channel in text_channels_for_guild(guild)}
    if source_channel_id and source_channel_id not in channel_ids:
        errors.append("Source channel must belong to the selected guild.")
    if mirror_channel_id and mirror_channel_id not in channel_ids:
        errors.append("Mirror channel must belong to the selected guild.")
    if (
        source_channel_id
        and mirror_channel_id
        and source_channel_id == mirror_channel_id
    ):
        errors.append("Source and mirror channels must be different.")

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

    return (
        GuildTranslationSettings(
            guild_id=guild.id,
            source_channel_id=int(source_channel_id) if source_channel_id else None,
            mirror_channel_id=int(mirror_channel_id) if mirror_channel_id else None,
            source_lang=source_lang,
            mirror_lang=mirror_lang,
            providers={
                direction_key(source_lang, mirror_lang): source_to_mirror_provider,
                direction_key(mirror_lang, source_lang): mirror_to_source_provider,
            },
            auto_rewrite_enabled=bool(form.get("auto_rewrite_enabled")),
            auto_rewrite_threshold=threshold_int,
            llm_extra_instructions=extra_instructions,
        ),
        errors,
    )


def dashboard_oauth_configured():
    return bool(
        config.DASHBOARD_DISCORD_CLIENT_ID
        and config.DASHBOARD_DISCORD_CLIENT_SECRET
        and config.DASHBOARD_DISCORD_REDIRECT_URI
    )


def exchange_discord_oauth_code(code):
    response = requests.post(
        DISCORD_OAUTH_TOKEN_URL,
        data={
            "client_id": config.DASHBOARD_DISCORD_CLIENT_ID,
            "client_secret": config.DASHBOARD_DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.DASHBOARD_DISCORD_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=8,
    )
    response.raise_for_status()
    return response.json()


def discord_api_get(path, access_token):
    response = requests.get(
        f"{DISCORD_API_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=8,
    )
    response.raise_for_status()
    return response.json()


def authorized_dashboard_guilds():
    user = session.get("discord_user") or {}
    user_id = int(user.get("id") or 0)
    bot_guilds = {guild.id: guild for guild in client.guilds}

    if not config.DASHBOARD_AUTH_ENABLED or user_id in config.ADMIN_IDS:
        return sorted(bot_guilds.values(), key=lambda guild: guild.name.casefold())

    authorized_ids = set()
    for guild in session.get("discord_guilds") or []:
        try:
            guild_id = int(guild["id"])
            permissions = int(guild.get("permissions") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if guild.get("owner") or permissions & DISCORD_ADMINISTRATOR_PERMISSION:
            authorized_ids.add(guild_id)

    return sorted(
        (guild for guild_id, guild in bot_guilds.items() if guild_id in authorized_ids),
        key=lambda guild: guild.name.casefold(),
    )


def selected_dashboard_guild_id(guilds, form=None):
    source = form if form is not None else request.args
    raw_guild_id = source.get("guild_id") if source is not None else None
    allowed_ids = {guild.id for guild in guilds}

    try:
        guild_id = int(raw_guild_id) if raw_guild_id else None
    except (TypeError, ValueError):
        guild_id = None

    if guild_id in allowed_ids:
        return guild_id
    if guilds:
        return guilds[0].id
    return None


def guild_by_id(guild_id):
    if guild_id is None:
        return None
    return client.get_guild(int(guild_id))


def text_channels_for_guild(guild):
    if guild is None:
        return []
    return sorted(
        [
            channel
            for channel in getattr(guild, "text_channels", [])
            if getattr(channel, "id", None)
        ],
        key=lambda channel: (getattr(channel, "position", 0), channel.name.casefold()),
    )


def schedule_translation_settings_reload():
    translation_cog = client.get_cog("Translation")
    if translation_cog is None:
        return False

    future = asyncio.run_coroutine_threadsafe(
        translation_cog.reload_settings(),
        client.loop,
    )
    future.add_done_callback(log_translation_reload_result)
    return True


def log_translation_reload_result(future):
    try:
        future.result()
    except Exception:
        logger.warning("Failed to live-reload translation settings.", exc_info=True)
    else:
        logger.info("Live-reloaded translation settings from dashboard.")


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
