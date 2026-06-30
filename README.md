# Bard

A simple music bot built with [discord.py](https://github.com/Rapptz/discord.py) that uses YouTube to stream songs. Bard also uses an experimental extension for processing vocal instructions.

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

### Vocal Commands

**_WARNING!_** _These features are based on an [experimental extension](https://github.com/imayhaveborkedit/discord-ext-voice-recv) of the discord.py wrapper. They can break at any time and are not actively maintained._

Bard uses local wake words powered by openWakeWord to avoid misinterpreting normal speech as commands. The default wake phrase is "hey jarvis" because it is one of openWakeWord's built-in models. You can configure wake models with `ASSISTANT_WAKEWORD_MODELS`, or point that setting at a custom trained model.

Voice commands are disabled by default. Set `ASSISTANT_ENABLED=true` to enable the assistant module. You can instruct Bard by issuing your commands vocally while on a call with her. First type `?join` while on a call and then say the configured wake phrase. If Bard heard you correctly, you will hear a reply. Bard will listen for one command, transcribe it, and parse it with local rules. The parser understands common music-control requests like "play Daft Punk", "can you play some jazz", "pause the song", "resume", "skip this", "what song is this", "loop this song", and "disconnect".

Bard can optionally use OpenRouter as a fallback parser when local rules do not understand a command. Set `ASSISTANT_LLM_PROVIDER=openrouter`, `ASSISTANT_OPENROUTER_API_KEY=<key>`, and `ASSISTANT_OPENROUTER_MODEL=<model id>` to enable it. If the LLM is unavailable, slow, or returns an unclear result, Bard falls back to asking for clarification rather than guessing.

_Remember! Due to technical reasons, Bard will only listen to the **first speaker** who invited her to the
voice channel. So to make yourself the priority speaker, just disconnect Bard and invite her to the call
yourself using_ `?join`.

### Translation Mirrors

Bard can mirror text between paired channels in different languages. Translation is disabled by default and currently supports the local Argos Translate provider.

Example `.env` configuration:

```env
TRANSLATION_ENABLED=true
TRANSLATION_PROVIDER=argos
TRANSLATION_CHANNEL_PAIRS=123456789012345678:234567890123456789:en:fr
TRANSLATION_MAX_CONCURRENCY=1
TRANSLATION_CACHE_SIZE=1000
TRANSLATION_USE_WEBHOOKS=true
WRITING_FEEDBACK_ENABLED=true
WRITING_FEEDBACK_AUTO_REPLY=false
WRITING_FEEDBACK_PROVIDER=grammalecte
WRITING_FEEDBACK_LANGUAGES=fr
WRITING_FEEDBACK_SCORE_THRESHOLD=75
WRITING_FEEDBACK_RECOMMEND_THRESHOLD=45
WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD=25
WRITING_FEEDBACK_LLM_PROVIDER=gemini
WRITING_FEEDBACK_GEMINI_API_KEY=<your Google AI Studio Gemini API key>
WRITING_FEEDBACK_GEMINI_MODEL=gemini-3.5-flash
WRITING_FEEDBACK_LLM_RATE_LIMIT_COOLDOWN_SECONDS=300
```

`TRANSLATION_CHANNEL_PAIRS` uses `source_channel_id:mirror_channel_id:source_lang:mirror_lang`. Bard mirrors both directions, so the example above translates English messages into French in the mirror channel and French replies back into English in the source channel.

When `TRANSLATION_USE_WEBHOOKS=true`, Bard sends mirrored translations through a channel webhook named `Bard Translation Mirror` using the original author's display name and avatar. This makes mirror channels look closer to the source channel. Bard needs `Manage Webhooks` in each mirror channel for this; if webhook sending fails, Bard falls back to a normal bot message.

When writing feedback is enabled, Bard can check messages written in the mirror channel for the configured foreign language. For French, Bard uses Grammalecte to produce a rule-based writing score from grammar, typography, and suggestion density. Feedback is on demand by default: right-click or long-press a mirror-channel message and choose `Apps > French Feedback`, or react with `📝` to request basic feedback in the channel. Basic feedback is rule-based and does not call the LLM.

For a fuller LLM rewrite, choose `Apps > French Rewrite` or react with `✨`. Bard asks Gemini for a natural rewrite plus short English notes focused on corrections and the reasoning behind them. Rewrite requests post the original message, natural rewrite, and notes inline. Scores at or below `WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD` also trigger an LLM rewrite automatically when feedback is requested. Set `WRITING_FEEDBACK_AUTO_REPLY=true` to restore automatic feedback replies for messages at or below `WRITING_FEEDBACK_SCORE_THRESHOLD`.

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
