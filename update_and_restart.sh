#!/bin/bash

pip install -U --pre "yt-dlp[default]"
pkill -f watcher.py
sleep 5
cd ~/bard || exit 1
nohup python bot/watcher.py &