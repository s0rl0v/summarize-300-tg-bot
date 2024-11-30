import logging
import os
import re
import time

import requests
from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)


class MessageBuffer:
    MAX_LIMIT = 4096  # Telegram one message character limit

    def __init__(self) -> None:
        self.messages = []
        self.current = None

    def __iter__(self):
        self.index = 0
        return self

    def __next__(self):
        if self.index <= self.current:
            result = self.messages[self.index]
            self.index += 1
            return result
        else:
            raise StopIteration

    def add(self, message: str) -> None:
        if self.current is None:
            self.messages.append("")
            self.current = 0
        elif len(self.messages[self.current]) + len(message) > MessageBuffer.MAX_LIMIT:
            self.messages.append("")
            self.current += 1

        self.messages[self.current] += message


class Summarize300Client:
    ENDPOINT = "https://300.ya.ru/api/generation"
    MAX_RETRIES = 100

    def __init__(self, yandex_oauth_token, yandex_cookie) -> None:
        self.headers = {
            "Authorization": f"OAuth {yandex_oauth_token}]",
            "Cookie": yandex_cookie,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.967 YaBrowser/23.9.1.967 Yowser/2.5 Safari/537.36",
            "Referer": "https://300.ya.ru/summary",
            "Origin": "https://300.ya.ru",
            "pragma": "no-cache",
            "cache-control": "no-cache",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en,ru;q=0.9,tr;q=0.8",
            "Cache-Control": "no-cache",
            "Content-Length": "59"
        }
        self.buffer = MessageBuffer()

    def __send_request(self, json):
        response = requests.post(
            Summarize300Client.ENDPOINT, json=json, headers=self.headers
        )
        return response

    def __parse_article_summarization_json(self, url, data) -> None:
        if "chapters" not in data:
            logging.error("{url}: there's no 'thesis' in response body")
            raise Exception
        self.buffer.add(f"<b>{data['title']}</b>\n\n")
        for chapter in data["chapters"]:
            self.buffer.add(f"<b>{chapter['content']}</b>\n")
            for thesis in chapter["theses"]:
                self.buffer.add(f"\t• {thesis['content']}")
                if "link" in thesis and thesis["link"]:
                    self.buffer.add(f"<a href=\"{thesis['link']}\">Link</a>")
                self.buffer.add("\n")
            self.buffer.add("\n")
        self.buffer.add("\n")

    def __parse_video_summarization_json(self, url, data) -> None:
        if "error_code" in data:
            msg = f"The video is not supported, Yandex API returned error_code {data['error_code']}"
            logging.error(msg)
            self.buffer.add(msg)
            return
        if "keypoints" not in data:
            logging.error(f"{url}: there's no 'keypoints' in response")
            raise Exception
        self.buffer.add(f"{data['title']}\n")
        for keypoint in data["keypoints"]:
            self.buffer.add(
                f'<a href="{url}&t={keypoint["start_time"]}">{int(int(keypoint["start_time"])/60/60 % 60):02}:{int(int(keypoint["start_time"])/60 % 60):02}:{int(int(keypoint["start_time"]) % 60):02}</a> {keypoint["content"]}\n'
            )
            for thesis in keypoint["theses"]:
                self.buffer.add(f"\t• {thesis['content']}\n")
            self.buffer.add("\n")

    def summarize(self, text):
        json_payload = {}
        if "youtu" in text:
            json_payload["video_url"] = text
            json_payload["type"] = "video"
            parse_selector = self.__parse_video_summarization_json
        elif "http" in text:
            json_payload["article_url"] = text
            json_payload["type"] = "article"
            parse_selector = self.__parse_article_summarization_json
        else:
            json_payload["text"] = text
            json_payload["type"] = "text"
            parse_selector = self.__parse_article_summarization_json

        counter = 0
        status_code = None
        while (
            status_code != 0 and status_code != 2
        ) and counter < Summarize300Client.MAX_RETRIES:
            counter += 1
            response = self.__send_request(json=json_payload)
            if response.status_code != 200:
                raise Exception(f"Yandex 300 API returned {response.status_code}")
            response_json = response.json()
            logging.debug(response_json)
            if "status_code" not in response_json:
                logging.error(f"{text} backend error: {response_json}")
                self.buffer.add("Yandex API is not available, try again later")
                return self.buffer
            status_code = response_json["status_code"]
            if status_code >= 3:
                if "text" in json_payload["type"]:
                    self.buffer.add(
                        f"Yandex API returned status_code {status_code} when processing text summarization request, are you sure that text lenght is more than 300 characters?"
                    )
                else:
                    self.buffer.add(
                        f"Yandex API returned status_code {status_code} when processing request, the link is not supported by Yandex backend"
                    )
                return self.buffer
            if "poll_interval_ms" in response_json:
                poll_interval_ms = response_json["poll_interval_ms"]
                time.sleep(poll_interval_ms / 1000)

            if "session_id" not in json_payload:
                session_id = response_json["session_id"]
                json_payload["session_id"] = session_id

        parse_selector(text, response_json)

        return self.buffer


async def processing_helper(
    text: str, update: Update, context: ContextTypes.DEFAULT_TYPE
):
    logging.debug(f"Processing {text}")
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id, action=ChatAction.TYPING
    )
    summarizer = Summarize300Client(
        yandex_oauth_token=context.bot_data["YANDEX_OAUTH"],
        yandex_cookie=context.bot_data["YANDEX_COOKIE"],
    )
    try:
        buffer = summarizer.summarize(text)
    except Exception as e:
        logging.debug(f"500 Internal server error: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="500 Internal Server Error, ping @sorloff",
            parse_mode="html",
            reply_to_message_id=update.message.id,
        )
        return

    for message in buffer.messages:
        logging.debug(
            f"Will be sending to {update.effective_user.name} len {len(message)}: {message}"
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode="html",
            reply_to_message_id=update.message.id,
        )


async def reply_helper(
    message: Message, update: Update, context: ContextTypes.DEFAULT_TYPE
):
    matches = re.findall("(?P<url>https?://[^\\s&]+)", message.text)

    if not matches:
        await processing_helper(message.text, update, context)
    else:
        logging.debug(f"Found matches: {matches}")

        for match in matches:
            await processing_helper(match, update, context)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.debug(f"{update.effective_user.username}: {update.message.text}")
    if update.effective_message.reply_to_message:
        logging.debug(
            f"Reply2: {update.effective_message.reply_to_message.from_user}: {update.effective_message.reply_to_message.text}"
        )

    if update.effective_message.reply_to_message:
        await reply_helper(update.effective_message.reply_to_message, update, context)
    else:
        await reply_helper(update.effective_message, update, context)


if __name__ == "__main__":
    application = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    echo_handler = MessageHandler(
        filters.TEXT
        & (
            filters.Mention("Summarize300Bot")
            & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)
            | filters.ChatType.PRIVATE
        ),
        message_handler,
    )
    application.bot_data["YANDEX_OAUTH"] = os.environ["YANDEX_OAUTH"]
    application.bot_data["YANDEX_COOKIE"] = os.environ["YANDEX_COOKIE"]
    application.bot_data["DEVELOPER_CHAT_ID"] = os.environ["DEVELOPER_CHAT_ID"]

    application.add_handler(echo_handler)

    application.run_polling()
