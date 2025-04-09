# Bard

A simple music bot built using [discord.py](https://github.com/Rapptz/discord.py). Bard also uses an experimental extension for processing vocal instructions.

Bard was created for personal use. It will not work across multiple guilds.

## How do I run it?

Before you begin, make sure you have Python v3.8 or above installed.

1. Download the repository as a zip or clone it.

2. Make sure you are in the project's root directory. This means that you should only see the `bot` folder in your file explorer and not its contents.

3. Launch the shell (command prompt on Windows) in the directory you are currently on. If you are on Windows, enter `cmd` into the address bar in Windows Explorer. After you've launched the shell, enter the command `pip install -r requirements.txt`

4. [Download](https://ffmpeg.org/download.html) and install FFmpeg. You must also set the PATH environment variable to FFmpeg's installation directory, which is _usually_ `C:\ffmpeg\bin`

5. If you do not already have a Discord bot application ready, then [create one](https://discord.com/developers/applications).

6. Save the token generated for your bot. This token essentially acts as a credential for your application to run.

7. In the same directory, create a new file called `.env` and paste this text `TOKEN=<your token here>` into the file. Replace `<your token here>` with your bots's token. Your token must not contain "<" and ">".

8. In the same shell that we launched in step 3, launch the bot with this command `python -m bot.main`

You only need to type the last command if you need to restart the bot in the future.

## Features

### Music

Bard can play songs on demand and manages queued songs using an internal playlist. If this queue is exhausted, then Bard will continue playing randomly selected songs automatically until another song is queued to override it.

### Web Dashboard

Bard hosts a web dashboard that is accessible on your machine's address on port 5000. If you are on the same machine that Bard is hosted on, you can access the dashboard on http://127.0.0.1:5000.

### Vocal Commands

**_WARNING!_** _These features are based on an [experimental extension](https://github.com/imayhaveborkedit/discord-ext-voice-recv) of the discord.py wrapper. They can break at any time and are not actively maintained! You also need a picovoice account_.

You can instruct Bard by issuing your commands vocally while on a call with her. Usually, this would mean first typing out `?join` while on a call and then just saying your commands out aloud. While on call, Bard will try to decipher intent from your speech using [picovoice's Rhino](https://picovoice.ai/platform/rhino/).

To ask Bard to play a song, simply say "Play some music". If Bard correctly heard you, she will reply asking you to name the song that you want to play followed by silence. This silence is your cue to speak. After saying the name of your song, wait patiently since transcription can take time. Once the transcription is a success, Bard will look up your query on YouTube and queue the most relevant result. All of this is essentially the same as typing out the `?play` command but instead done vocally with zero keyboard interaction.

You can get a list of all speech to intent patterns by giving the command `?intents`

_Remember! Due to technical reasons, Bard will only listen to the **first speaker** who invited her to the voice channel. So to make yourself the priority speaker, just disconnect Bard and invite her to the call yourself using_ `?join`.

Bard also features wake word support, thanks to [picovoice's Porcupine](https://picovoice.ai/docs/porcupine/). This feature is currently disabled though but will work fine if enabled. It can be cumbersome because Bard will receive commands only after you say "OK Bard" every time for each command.

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

1. The bot cannot play age restricted videos. A temporary workaround is to simply queue a reposted version of the video that has not yet been flagged.

2. It does not support use across multiple guilds at once.

3. Some dependencies update with breaking changes. There's nothing that can be done about it other than freezing the requirements at a specific version. You may do this if you wish in your clone/fork of the repository. I've chosen not to since YT especially can undergo huge API changes which will require a library update anyways and some inevitable rewrite.

4. At times, YouTube may flag you as a bot. This will prevent you from being able to queue any songs. You can resolve this issue by updating yt-dlp or providing a cookie file.
