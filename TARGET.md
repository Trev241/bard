# TARGET

## What This Repository Is

This repository contains **Bard**, a personal Discord bot built mainly for music playback in a Discord voice channel.

Bard is not designed as a public multi-server product. It is currently meant for personal use, likely in one main Discord guild at a time.

The bot is written in Python using `discord.py`. It also runs a small Flask web dashboard with Socket.IO so playback can be viewed and controlled from a browser.

## Main Aim

The main goal of Bard is:

1. Join a Discord voice channel.
2. Search for music on YouTube.
3. Stream audio into the voice channel.
4. Manage a queue of requested songs.
5. Provide both Discord commands and a local web dashboard for controlling playback.

## Core Features

### Music Playback

Bard can:

- Join and leave Discord voice channels.
- Search YouTube using `yt-dlp`.
- Play individual songs or playlists.
- Queue songs requested by users.
- Skip one or more songs.
- Remove songs from the queue.
- Pause and resume playback.
- Show the current song.
- Show the queue.
- Loop the current track.
- Loop the queue.
- Automatically play random songs from a configured YouTube playlist when the queue is empty.

Important files:

- `bot/cogs/music.py`
- `bot/core/playback.py`
- `bot/core/models.py`

### Web Dashboard

Bard hosts a local Flask dashboard, normally at port `5000`.

The dashboard can:

- Show the currently playing track.
- Show track thumbnails.
- Show the upcoming queue.
- Submit new song requests.
- Pause or resume playback.
- Skip tracks.
- Toggle looping.

Socket.IO is used to keep the dashboard in sync with Discord playback events.

Important files:

- `bot/dashboard/app.py`
- `bot/dashboard/templates/dashboard.html`
- `bot/dashboard/static/index.js`

### Discord Utilities

Bard includes extra Discord helper behavior:

- Repeatedly ping users until they respond.
- Stop pinging a user once they send a message.
- Automatically start pinging if repeated mentions are detected.
- Send sticker/image files when certain words are detected.
- Parse time expressions for users with timezone role names and offer converted times.
- Save YouTube cookie files when a message attachment is reacted to with the configured cookie emoji.
- Restart or shut down the bot from Discord commands.
- Read recent runtime log snippets from Discord for debugging.
- Let users submit issue reports through a Discord form that creates GitHub issues.

Important files:

- `bot/cogs/utils.py`
- `bot/cogs/events.py`
- `bot/core/github_issues.py`

### Logging And Debugging

Bard writes runtime logs to a rotating log file so errors can be inspected after the fact without unbounded log growth.

Logs can be accessed through:

- The dashboard at `/dashboard/logs`.
- The trusted Discord `?logs` command for a recent snippet.
- The trusted Discord `?logs full` command for the current log file.

Important files:

- `bot/core/logging_service.py`
- `bot/dashboard/templates/logs.html`
- `bot/cogs/utils.py`

### Yordle

Bard includes a League of Legends champion-name guessing game inspired by Wordle.

The bot fetches champion data from Riot's Data Dragon API and generates image hints with Pillow.

Important file:

- `bot/cogs/wordle.py`

### Voice Assistant

There is an experimental voice assistant module using:

- Picovoice Porcupine for wake-word detection.
- Picovoice Rhino for speech-to-intent.
- `SpeechRecognition` and Whisper for transcription.
- `pyttsx3` for text-to-speech.
- `discord-ext-voice-recv` for receiving voice audio.

This module appears to be disabled in `bot/main.py` at the moment.

Important file:

- `bot/cogs/assistant.py`

## Runtime Shape

The main startup command is:

```bash
python -m bot.main
```

`bot/main.py` starts the Discord bot in a worker thread and then starts the Flask dashboard.

There is also a watcher script:

```bash
python bot/watcher.py
```

The watcher starts the bot, watches for restart signal files, can pull changes from Git, refresh `yt-dlp`, and restart the process.

## Important Assumptions

- The bot needs a Discord token in `.env` as `TOKEN=...`.
- The bot needs FFmpeg available on the system path.
- YouTube playback uses `yt-dlp`.
- YouTube cookies may be stored at `bot/secrets/cookies.txt`.
- The bot currently assumes a small/personal deployment.
- Multi-guild support is not a current design goal.
- Some folders are created automatically at import/startup, such as `bot/logs`, `bot/resources/dumps`, `bot/resources/stickers`, and `bot/secrets`.

## Current Design Strengths

- The repository is small and understandable.
- Features are organized mostly by Discord cog.
- Music playback is separated somewhat into `PlaybackManager`.
- The dashboard is useful and directly connected to playback events.
- The watcher script supports a lightweight self-hosted deployment flow.
- The watcher refreshes `yt-dlp` before restarts by default because YouTube extraction can break when `yt-dlp` falls out of date.
- Runtime logs are centralized, rotated, redacted, and visible from both Discord and the dashboard.

## Known Weak Spots

### Encoding Problems

Many Discord messages contain mojibake where emoji or symbols were decoded incorrectly.

Future work should either restore the intended Unicode characters or replace them with plain text.

### Heavy Global Initialization

`bot/__init__.py` creates the Discord client, Flask app, Socket.IO object, logging handlers, folders, and public URL detection at import time.

This works, but it makes testing and startup harder to reason about.

### Scattered Configuration

Settings such as ports, playlist URLs, channel IDs, file paths, webhook secrets, restart signal paths, cookie paths, and public URLs are spread across the codebase.

A central config module would make the project easier to maintain.

### Bare `except` Blocks

Several places catch all exceptions and either ignore them or hide useful context.

This can make playback, dashboard rendering, restart behavior, and Discord API failures difficult to debug.

### Tight Coupling

The music playback stack has been split into adapter, service, playback, and resolver layers. Future changes should preserve those boundaries.

### Limited Tests

The repository includes test dependencies, but there does not appear to be focused test coverage for queue behavior or playback control.

The highest-value tests would target `PlaybackManager`.

## Recommended Future Improvements

Priority improvements:

1. Fix broken text encoding in bot messages.
2. Add or maintain admin/owner checks for sensitive commands such as `shutdown`, `restart`, `logs`, cookie updates, and mass pinging.
3. Replace bare `except` blocks with logged exceptions.
4. Move config values into a central `bot/config.py` module.
5. Extract shared YouTube/`yt-dlp` options into one place.
6. Add focused unit tests for `PlaybackManager` queue behavior.
7. Keep the voice assistant behind an explicit feature flag until it is actively maintained.
8. Add useful npm scripts for rebuilding dashboard CSS.
9. Keep the single-guild assumption explicit unless a future task changes the architecture.

## Suggested Development Direction

Future sessions should preserve Bard's identity as a personal Discord music bot with a useful local dashboard.

Prefer reliability and maintainability over adding broad new product features.

When making changes:

- Keep behavior compatible with the existing `?` command interface.
- Avoid unrelated rewrites.
- Protect user/runtime data such as `.env`, `bot/secrets`, and generated dumps.
- Test queue and playback behavior carefully when touching music code.
- Treat dashboard changes and Discord playback changes as connected because they communicate through Socket.IO events.
