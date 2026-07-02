# Bard

A simple music bot built with [discord.py](https://github.com/Rapptz/discord.py) that uses YouTube to stream songs.

Bard was created for personal use in mind so it will not work across multiple guilds.

## How do I run it?

Before you begin, make sure you have Python v3.8 or above installed.

1. Download the repository as a zip or clone it.
2. Make sure you are in the project's root directory. This means that you should see the `bot` folder in your file explorer and not the `bot` folder's contents.
3. Launch the terminal (command prompt on Windows) in the directory that you are currently in. If you are on Windows, you can do this by entering `cmd` into the address bar in your File Explorer. Once the terminal is up, enter this command: `pip install -r requirements.txt`
4. [Download](https://ffmpeg.org/download.html) and install ffmpeg. You must also edit your environment variables by adding ffmpeg to your PATH. For Windows, you will usually find your ffmpeg installation in `C:\ffmpeg\bin`
5. If you do not already have a Discord bot application ready, then [create one](https://discord.com/developers/applications).
6. Save the token generated for your bot. This token is basically like your password to run your application.
7. In the same directory, create a new file called `.env` and paste this text `TOKEN=<your token here>` into the file. Replace `<your token here>` with your bots's token. Your token must not contain "<" and ">".
8. In the terminal that we launched before in step 3, start the bot by typing this command: `python -m bot.main`. You only need to type the last command again if you need to restart the bot in the future.

### Optional steps

1. In the same terminal from before, enter this command: `cd bot/dashboard && npm install && cd ../..` This will install the dependencies needed for the bot's web dashboard.
2. Run the bot by typing: `python -m bot.main`.

You can also launch the bot by typing this command instead: `python bot/watcher.py`. This script uses watchdog to monitor JSON files dumped by the bot whenever it receives a webhook request from GitHub. Its useful in cases where a reboot is needed whenenver the repository is updated. You can change the target file being monitored to whatever you like.

## Features

### Music

Bard can play songs on demand and manages all queued songs using an internal queue. If this queue is exhausted, a randomly selected song is played automatically until another one is queued to override it. All music played on Bard is streamed from YouTube through [yt-dlp](https://github.com/yt-dlp/yt-dlp).

### Web Dashboard

Bard hosts a web dashboard that is accessible on your machine's IP address on port 5000. If you are on the same machine that the bot is hosted on, you can access it at http://127.0.0.1:5000.

Translation mirror settings can be edited at `/dashboard/translation`. The page writes guild-specific non-secret settings to `bot/resources/translation/settings.json` and live-reloads the running translation cog after saving.

Dashboard routes are protected with Discord OAuth by default. Configure these values in `.env`:

```env
DASHBOARD_AUTH_ENABLED=true
DASHBOARD_SECRET_KEY=<random session secret>
DASHBOARD_DISCORD_CLIENT_ID=<Discord application client ID>
DASHBOARD_DISCORD_CLIENT_SECRET=<Discord application client secret>
DASHBOARD_DISCORD_REDIRECT_URI=http://127.0.0.1:5000/dashboard/auth/callback
```

The OAuth redirect URI must also be added to the Discord application. Logged-in users can administer dashboard translation settings for guilds where they have Discord Administrator permission; users listed in `BARD_ADMIN_IDS` can access every guild Bard is in.

### Translation Mirrors

Bard can mirror text between paired channels in different languages. Translation is disabled by default and supports the local Argos Translate provider or Gemini through the configured Gemini API key and model.

Example `.env` configuration:

```env
TRANSLATION_ENABLED=true
TRANSLATION_MAX_CONCURRENCY=1
TRANSLATION_CACHE_SIZE=1000
TRANSLATION_PERSISTENT_CACHE_ENABLED=true
TRANSLATION_CACHE_FILE=bot/resources/translation/cache.sqlite3
TRANSLATION_USE_WEBHOOKS=true
TRANSLATION_NORMALIZE_SLANG=true
WRITING_FEEDBACK_ENABLED=true
WRITING_FEEDBACK_PROVIDER=grammalecte
WRITING_FEEDBACK_LANGUAGES=fr
WRITING_FEEDBACK_SCORE_THRESHOLD=75
WRITING_FEEDBACK_RECOMMEND_THRESHOLD=45
WRITING_FEEDBACK_LLM_PROVIDER=gemini
WRITING_FEEDBACK_GEMINI_API_KEY=<your Google AI Studio Gemini API key>
WRITING_FEEDBACK_GEMINI_MODEL=gemini-3.5-flash
WRITING_FEEDBACK_LLM_RATE_LIMIT_COOLDOWN_SECONDS=300
```

Bard loads translation channel pairs and per-direction engines from `bot/resources/translation/settings.json`, which is managed through the dashboard translation settings page. If a guild is missing source channel, mirror channel, language codes, or either direction's translation provider in that settings file, translation mirroring is unavailable for that guild instead of falling back to `.env`.

`TRANSLATION_CACHE_SIZE` controls the maximum number of cached translations. When `TRANSLATION_PERSISTENT_CACHE_ENABLED=true`, Bard stores those entries in `TRANSLATION_CACHE_FILE` so repeated phrases survive restarts. Cache entries are scoped by guild, language direction, normalized text, and selected translation route.

When `TRANSLATION_USE_WEBHOOKS=true`, Bard sends mirrored translations through a channel webhook named `Bard Translation Mirror` using the original author's display name and avatar. This makes mirror channels look closer to the source channel. Bard needs `Manage Webhooks` in each mirror channel for this; if webhook sending fails, Bard falls back to a normal bot message.

When `TRANSLATION_NORMALIZE_SLANG=true`, Bard normalizes common casual English before sending text to Argos. This helps local translation models handle phrases like `ur using an llm`, `don't bs me`, and `vas` more consistently. Set it to `false` if you want raw Argos translation input. Slang rules live in `bot/resources/translation/normalization.en.json`; add new ordered `pattern` and `replacement` entries there when Bard needs to understand more chat shorthand.

When writing feedback is enabled, Bard can check messages written in the mirror channel for the configured foreign language. For French, Bard uses Grammalecte to produce a rule-based writing score from grammar, typography, and suggestion density. Feedback is on demand by default: right-click or long-press a mirror-channel message and choose `Apps > French Feedback`, or react with `📝` to request basic feedback in the channel. Basic feedback is rule-based and does not call the LLM. Automatic feedback replies run after the translated message is mirrored, so feedback and rewrite latency does not delay the translation send path.

For a fuller LLM rewrite, choose `Apps > French Rewrite` or react with `✨`. Bard asks Gemini for a natural rewrite plus short English notes focused on corrections and the reasoning behind them. Rewrite requests post the original message, natural rewrite, and notes inline. Automatic feedback/rewrite behavior, rewrite threshold, and extra LLM instructions are configured per guild from the dashboard translation settings page.

The `French Feedback` and `French Rewrite` context menus are Discord app commands. Bard syncs them to each connected server on startup, so restart Bard after enabling translation feedback. If the commands do not appear under `Apps`, make sure the bot was invited with the `applications.commands` scope and that you have permission to use application commands in the channel.

If `WRITING_FEEDBACK_LLM_PROVIDER=gemini`, Bard asks Gemini through the Google AI Studio Gemini API only for explicit rewrite requests. `WRITING_FEEDBACK_GEMINI_MODEL` accepts a comma-separated priority list; Bard tries the next model if one returns a rate limit, timeout, or temporary service error. If every configured model is unavailable or rate-limited, Bard falls back to Grammalecte's rule-based suggestion. After all configured models return 429, Bard pauses LLM rewrite requests for `WRITING_FEEDBACK_LLM_RATE_LIMIT_COOLDOWN_SECONDS`.

LLM rewrites include a small conversation context window: the Discord message being replied to, when present, and the immediately previous human message in the mirror channel. Bard excludes bot messages, mirrored translation messages, and feedback replies from this context.

Install the Python packages with `pip install -r requirements.txt`, then install the required Argos language models on the host running Bard:

```bash
argospm update
argospm install translate-en_fr
argospm install translate-fr_en
```

Bard warms up the configured Argos language pairs when the translation cog loads. This front-loads Argos' installed-language scan during startup so the first mirrored message does not pay the full cold-start cost.

## List of available commands

The bot's prefix is `?`. Some commands have aliases which have not been mentioned for the sake of brevity. Only some of the commands have been included. For a full list, do `?help` when the bot is up and running.

1.  `play <query>`
2.  `skip [count]`
3.  `loop` to loop a single track or `loop queue` to loop the queue.
4.  `remove <index>`
5.  `queue`
6.  `now`
7.  `pause`
8.  `resume`
9.  `disconnect`
10. `join`

## Known issues

1. Bard cannot play age restricted videos. A temporary workaround is to simply queue a reposted version of the video that has not yet been flagged.
2. It does not support use across multiple guilds at once.
3. YouTube is notorious for refusing playback if it suspects you of botting or violating ToS. This will not allow you to play any music. The current workaround is to frequently update yt-dlp. Look into nightly builds if you are desperate.
