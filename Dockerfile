FROM node:lts
WORKDIR /bard
COPY . .

ENV $(cat .env | xargs)

WORKDIR bot
RUN set -xe \
    && apt-get update -y \
    && apt-get install -y ffmpeg \
    && apt-get install -y python3-full \
    && apt-get install -y python3-pip

RUN set -xe \
    && python3 -m venv venv

RUN set -xe \
    && . venv/bin/activate \
    && pip install -r requirements.txt \
    && pip install -U "discord.py[voice]" \
    && pip install pynacl

WORKDIR ../launcher
RUN npm install
EXPOSE 5000

CMD ["npm", "start"]
