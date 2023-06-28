# Local development

1. Have Python3 with pip ready (it's recommended to create venv)
2. run `pip install -r requirements.txt`
3. Register your TG bot with [BotFather](https://t.me/BotFather)
4. Copy your bot token and setup your `.env` (use `.env-example` as template)
5. DO NOT use https for local launch (not supported): so just don't include last two lines of .env-example when doing
   the previous step
6. Run `local-launch.sh`