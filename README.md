# Description
This is a simple Telegram bot that wraps 300 YandexGPT summarizer into Telegram interface.

# Technology stack
Python, python-telegram-bot.

# Usage
@Summarize300Bot or self-host it independently.

# Build

Install poetry and Python 3.12.
Then fill `.env` config inside the project directory:

```
TELEGRAM_BOT_TOKEN='***' // get from BotFather
YANDEX_OAUTH='***' // Click API link on https://300.ya.ru/ webpage and select "Generate token"
YANDEX_COOKIE='***' // Navigate to https://300.ya.ru/ and enable developer console, check in Network tab requests to /generation or /sharing_url endpoints on processing some article or video - you will find the value in 'Cookie' Header.
DEVELOPER_CHAT_ID='***' // This is your chat id, or whatever person you would like to receive exceptions
```

Then execute on the host machine:
```
# poetry install
# poetry run python main.py
```

Now you can query the bot.
