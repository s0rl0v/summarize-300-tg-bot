import html
import json
import os
import re
import time
import traceback
import requests
import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, filters, MessageHandler, ApplicationBuilder, ContextTypes

# TODO: write Dockerfile
# TODO: deployment variants (lambda vs vps)
# TODO: serverless?

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

class MessageBuffer:
    MAX_LIMIT = 4096 # Telegram one message character limit

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
    ENDPOINT = 'https://300.ya.ru/api/generation'
    MAX_RETRIES = 100

    def __init__(self, yandex_oauth_token, yandex_cookie) -> None:
        self.headers = {'Authorization': f'OAuth {yandex_oauth_token}]',
                    'Cookie' : yandex_cookie,
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.967 YaBrowser/23.9.1.967 Yowser/2.5 Safari/537.36",
                    "Referer": f'https://300.ya.ru/summary',
                    "Origin": f'https://300.ya.ru',
                    "pragma": "no-cache",
                    "cache-control": "no-cache",
                    "Accept": "*/*",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Accept-Language":"en,ru;q=0.9,tr;q=0.8",
                    "Cache-Control": "no-cache",
                    "Content-Length": "59",
                    "Content-Type": "application/json" }
        self.buffer = MessageBuffer()

    def __send_request(self, json):
        response = requests.post(
            Summarize300Client.ENDPOINT,
            json = json,
            headers = self.headers
        )
        return response

    def __parse_article_summarization_json(self, url, data) -> None:
        if not "thesis" in data:
            logging.error("{url}: there's no 'thesis' in response body")
            raise Exception
        self.buffer.add(f"{data['title']}\n\n")
        for keypoint in data['thesis']:
            self.buffer.add(f"\t• {keypoint['content']}")
            if "link" in keypoint:
                self.buffer.add(f"<a href=\"{keypoint['link']}\">Link</a>")
            self.buffer.add("\n")
        self.buffer.add("\n")

    def __parse_video_summarization_json(self, url, data) -> None:
        if 'error_code' in data:
            msg = f"{url} is not supported"
            logging.error(msg)
            self.buffer.add(msg)
            return
        if not "keypoints" in data:
            logging.error(f"{url}: there's no 'keypoints' in response")
            raise Exception
        self.buffer.add(f"{data['video_title']}\n")
        for keypoint in data['keypoints']:
            self.buffer.add(f'<a href="{url}&t={keypoint['start_time']}">{int(int(keypoint['start_time'])/60/60 % 60):02}:{int(int(keypoint['start_time'])/60 % 60):02}:{int(int(keypoint['start_time']) % 60):02}</a> {keypoint['content']}\n')
            for thesis in keypoint['theses']:
                self.buffer.add(f"\t• {thesis['content']}\n")
            self.buffer.add("\n")

    def summarize_url(self, url) -> None:
        json_payload = {}
        if "youtube" in url:
            json_payload['video_url'] = url
            parse_selector = self.__parse_video_summarization_json
        else:
            json_payload['article_url'] = url
            parse_selector = self.__parse_article_summarization_json

        counter = 0
        status_code = None
        while(( status_code != 0 and status_code != 2) and counter < Summarize300Client.MAX_RETRIES):
            counter += 1
            response = self.__send_request(json=json_payload)
            response_json = response.json()
            if 'status_code' not in response_json:
                logging.error(f"{url} backend error: {response_json}")
                self.buffer.add("Incorrect payload, 300 Yandex backend temporarily unavailable")
                return self.buffer

            status_code = response_json['status_code']
            if status_code > 3:
                logging.error(f"{url} returned status_code > 2")
                self.buffer.add("{url} is not eligible for summarization by Yandex LLM")
                return self.buffer
            if 'poll_interval_ms' in response_json:
                poll_interval_ms = response_json['poll_interval_ms']
                time.sleep(poll_interval_ms/1000)

            if 'session_id' not in json_payload:
                session_id = response_json['session_id']
                json_payload['session_id'] = session_id

        parse_selector(url, response_json)

        return self.buffer

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.debug(f"Got message {update.message.text} from {update.effective_user.username}")
    matches = re.findall("(?P<url>https?://[^\\s&]+)", update.message.text)
    if not matches:
        logging.debug("Got no links to process")
        await context.bot.send_message(chat_id=update.effective_chat.id, \
                                       text="Usage: send a link to article/youtube video in private or mention with the link in a group chat", \
                                       parse_mode='html')
    else:
        logging.debug(f"Found matches: {matches}")

        for match in matches:
            logging.debug(f"Processing URL: {match}")
            summarizer = Summarize300Client(yandex_oauth_token=context.bot_data['YANDEX_OAUTH'], \
                                            yandex_cookie=context.bot_data['YANDEX_COOKIE'])
            buffer = summarizer.summarize_url(match)

            for message in buffer.messages:
                logging.debug(f"Will be sending to {update.effective_user.name} len {len(message)}: {message}")
                await context.bot.send_message(chat_id=update.effective_chat.id, \
                                               text=message, parse_mode='html', \
                                               reply_to_message_id=update.message.id)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logging.error("Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        "An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    # Finally, send the message
    await context.bot.send_message(
        chat_id=context.bot_data['DEVELOPER_CHAT_ID'], text=message, parse_mode='html'
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, \
                                   text="Can't summarize the article. Contact the developer for clarifications.", \
                                    parse_mode='html')

if __name__ == '__main__':
    application = ApplicationBuilder().token(os.environ['TELEGRAM_BOT_TOKEN']).build()
    echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND) \
                                  & ((filters.Entity("mention") & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)) \
                                     | (filters.ChatType.PRIVATE)), message_handler)
    application.bot_data['YANDEX_OAUTH'] = os.environ['YANDEX_OAUTH']
    application.bot_data['YANDEX_COOKIE'] = os.environ['YANDEX_COOKIE']
    application.bot_data['DEVELOPER_CHAT_ID'] = os.environ['DEVELOPER_CHAT_ID']

    application.add_handler(echo_handler)
    application.add_error_handler(error_handler)

    application.run_polling()

