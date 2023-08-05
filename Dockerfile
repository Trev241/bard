FROM node:lts
WORKDIR /bard
COPY . .

ENV $(cat .env | xargs)

WORKDIR bot
RUN set -xe \
    && apt-get update -y \
    && apt-get install -y ffmpeg \
    && apt-get install -y python3 \
    && apt-get install -y pipx \
    && pipx install -r requirements.txt \
    && pipx install -U "discord.py[voice]" \
    && pipx install pynacl

WORKDIR ../launcher
RUN npm install
EXPOSE 5000

CMD ["npm", "start"]
