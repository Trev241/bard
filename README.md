# Bard

A simple Discord bot built on the [discord.py](https://github.com/Rapptz/discord.py) wrapper that offers basic commands for playing music on a server. It is intended for private use only.

## How do I run it?

The bot comes with a launcher that allows you to remotely boot up the bot. However, it is not absolutely necessary and is not the only way to start the bot. You may also manually boot up the bot locally on your system as you normally would, if that is what you prefer. 

### Without the launcher

Before you begin, an installation of Python v3.8 or above is required.

1. Download the repository as a zip and extract **only the `bot` folder**. Another way is to clone the repository and then later delete the `launcher` folder.

2. Open the `bot` folder and launch command prompt (or the shell or whatever equivalent exists on your operating system). In Windows, you can do this by entering `cmd` into the address bar at the top of the File Explorer.

3. In the command prompt window, enter the command below. This command will install the bot's Python dependencies.

```
pip install -r requirements.txt
```

4. [Download](https://ffmpeg.org/download.html) and install FFmpeg. Make sure to also set the PATH environment variable to wherever FFmpeg is installed. This will help the bot locate the binary executables when processing audio. The path is *usually* `C:\ffmpeg\bin`

5. If you do not already have a Discord bot application ready, then [create one](https://discord.com/developers/applications). 

6. Save the token generated for your bot. This token essentially acts as a credential for your application to run. 

7. In the same directory, create a new file called `.env` and paste the text below in it. Replace the placeholder text with your token as illustrated. and do not forget to remove the "<" and ">" symbols.

```
TOKEN=<your token here>
```

8. In the same command prompt window opened earlier, enter the command to start the bot.

```
python main.py
```

You only need to type the last command if you need to start the bot in the future.

### With the launcher

*This is only a brief guide that assumes you have experience with Docker and Node.*

Firstly, create a `.env` file in the root directory of the repository and paste the following contents

```
TOKEN=<your token here>
SECRET=<your secret here>
API_BASE_URL=<host url>
```

The bot can only be launched if the secret entered by the user through the browser matches the value of the `SECRET` environment variable. 

The `API_BASE_URL` should be the URL of your web-app. For example, the `API_BASE_URL` would be `http://localhost:5000` if it was hosted locally on port 5000. This is necessary since the bot will make a POST request to this address whenever it exits.

If your server or host system supports running Docker images, then use the Dockerfile in the repository to create a Docker image. Once the image has been created, run the Docker image and launch the bot from the web-app.

In case there is no Docker support, then you can always run the command `npm start` from the `launcher` subdirectory. For this step to work, you must ensure that you have installed all required dependencies, both JavaScript as well as Python, using the commands `npm install` and `pip install -r requirements.txt`.


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

10.  `join`

  

## Known issues

1. The bot cannot play age restricted videos. A temporary workaround is to simply query a reposted version of the video that has not yet been flagged.

2. Since the bot was created with private use in mind, it does not support use across multiple guilds at once.

3. The launcher relies on the bot to notify it whenever it exits. This can be problematic if the bot unexpectedly crashes and fails to make a POST request to the server.

4. Some dependencies update with breaking changes. There's nothing that can be done about it other than freezing the requirements at a specific version. You may do this if you wish in your clone/fork of the repository. I've chosen not to since YT especially can undergo huge API changes which will require a library update anyways and some inevitable rewrite.