FROM node:lts
WORKDIR /bard
COPY . .

ENV $(cat .env | xargs)

WORKDIR bot
RUN set -xe \
    && apt-get update -y \
    && apt-get install -y ffmpeg \
    && apt-get install -y python3 \
    && apt-get install -y python3-pip

RUN set -xe \
    && pip install -r requirements.txt \
    && pip install "discord.py[voice]" \
    && pip install pynacl

WORKDIR ../launcher
RUN npm install
EXPOSE 5000

CMD ["npm", "start"]
