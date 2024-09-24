FROM node:lts
WORKDIR /bard
COPY . .

ENV $(cat .env | xargs)
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR bot
RUN set -xe \
    && apt-get update -y \
    && apt-get install -y ffmpeg \
    && apt-get install -y python3-full \
    && apt-get install -y python3-pip \
    && apt-get install -y espeak-ng

RUN set -xe \
    && python3 -m venv venv

RUN set -xe \
    && . venv/bin/activate \
    && pip install -r requirements.txt \
    && pip install -U "discord.py[voice]" \
    && pip install pynacl

RUN apt-get update && apt-get install -y \
    wget \
    gnupg2 \
    apt-transport-https \
    ca-certificates \
    --no-install-recommends

RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable --no-install-recommends

RUN apt-get clean && rm -rf /var/lib/apt/lists/*


WORKDIR ../launcher
RUN npm install
EXPOSE 5000

CMD ["npm", "start"]
