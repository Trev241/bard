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

**_WARNING!_** _These features are based on an [experimental extension](https://github.com/imayhaveborkedit/discord-ext-voice-recv) of the discord.py wrapper. They can break at any time and are not actively maintained! You also need a picovoice account_.

Bard uses wake words supported by [picovoice's Porcupine](https://picovoice.ai/docs/porcupine/) to avoid misinterpreting normal speech as commands. You must always wake Bard up first by saying "Okay, Bard" before you issue any other command.

You can instruct Bard by issuing your commands vocally while on a call with her. First type `?join` while on a call and then say out loud "Okay, Bard". If Bard heard you correctly, you will hear a reply. Bard will then try to decipher intent from your speech using [picovoice's Rhino](https://picovoice.ai/platform/rhino/). You can get a list of all speech to intent patterns by typing out the command `?intents`.

To ask Bard to play a song, say "Play some music". She will reply asking you to name the song that you want to play followed by silence. This silence is your cue to speak. After saying the name of your song, wait patiently since
transcription can take time. Once Bard is done trying to make sense of your query, she will look it up on YouTube and queue the most relevant result. All of this is essentially the same as typing out the `?play` command but instead done vocally with zero keyboard interaction.

_Remember! Due to technical reasons, Bard will only listen to the **first speaker** who invited her to the
voice channel. So to make yourself the priority speaker, just disconnect Bard and invite her to the call
yourself using_ `?join`.

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
