FROM node:lts
WORKDIR /bard
COPY . .

ENV $(cat .env | xargs)

WORKDIR bot
RUN set -xe \
    && apt-get update -y \
    && apt-get install -y ffmpeg \
    && apt-get install -y python3 \
    && apt-get install -y python3-pip \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -U "discord.py[voice]" \
    && pip install pynacl \
    && git clone https://github.com/ytdl-org/youtube-dl.git dependencies/youtube-dl \
    && cd dependencies/youtube-dl \
    && pip install .

WORKDIR ../launcher
RUN npm install
EXPOSE 5000

CMD ["npm", "start"]
