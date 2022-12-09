# Bard

A simple Discord bot built on the [discord.py](https://github.com/Rapptz/discord.py) wrapper that offers basic commands for playing music on a server. It is intended for private use only.

## How do I run it?

Before you begin, an installation of Python v3.8 or above is required.

1. Download the repository as a zip and extract its contents into a folder. Alternatively, you may clone the repository as well. Open the project's folder and launch command prompt (or its equivalent for your operating system). Then type in the command below.
```
pip install -r requirements.txt
```
This command will install the required dependencies for the bot to work. 

2. There is also another dependency called FFmpeg that you must install separately. You can get its packages and executable files from this [link](https://ffmpeg.org/download.html). You must also set the PATH environment variable to the directory of these files.  

3. If you do not already have a Discord bot application ready, then you can create one [here](https://discord.com/developers/applications). Save the token generated for your bot. This token essentially acts as a credential for your application to run. In the same directory, create a new file named `config.json` and paste the following text in it.
```json
{
    "token": "<insert your token here>"
}
```
Replace your token in the space as mentioned above. Remember that your token must be enclosed within double quotes.

4. After performing all the necessary setup, you can simply run the bot by running the following command in the same command prompt window that you had opened earlier for installing the requirements.
```
python main.py
```

## List of available commands

The bot's prefix is `?`. Some commands have aliases which have not been mentioned for the sake of brevity

1. `play <query>`
2. `skip [count]` 
3. `loop`
	Sub command(s):
	1. `queue`
4. `remove <index>`
5. `queue`
5.  `now`
6. `pause`
7. `resume`
8. `disconnect`
9. `join`

## Known issues

1. The bot cannot play age restricted videos. A temporary workaround is to simply query a reposted version of the video that has not yet been flagged.