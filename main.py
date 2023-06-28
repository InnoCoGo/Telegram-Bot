import os
from typing import Tuple

import requests
from dotenv import load_dotenv
from flask import Flask
from flask import Response
from flask import request

app: Flask = Flask(__name__)
backend_variable: None | str = None


def get_tg_token() -> str:
    return os.getenv("TG_BOT_TOKEN")


def get_tg_secret_token() -> str:
    return os.getenv("TG_SECRET_TOKEN")


def parse_message(message) -> None | Tuple[str, str]:
    try:
        print("message-->", message)
        chat_id = message['message']['chat']['id']
        txt = message['message']['text']
        print("Text :", txt)
        return chat_id, txt
    except:
        return None


def tg_send_message(chat_id, text):
    url = f'https://api.telegram.org/bot{get_tg_token()}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text
    }

    response = requests.post(url, json=payload)
    return response


def handle_tg_update(chat_id, text):
    tg_send_message(chat_id, f"(v3) You said: '{text}'. The last backend endpoint request said: '{backend_variable}'")


@app.route('/telegram_endpoint', methods=['POST'])
def telegram_endpoint():
    token_received = request.headers.get('X-Telegram-Bot-Api-Secret-Token', 'no-key')
    if get_tg_secret_token() != token_received:
        print(f"Unauthorized! Tried to access with token {token_received}'")
        return Response(status=403)

    msg = request.get_json()
    parsed_message = parse_message(msg)
    if parsed_message is None:
        # Some kind of unhandled message came our way: we lie to Telegram, saying that we handled it
        return Response('ok', status=200)
    chat_id, text = parsed_message
    handle_tg_update(chat_id, text)

    return Response('ok', status=200)


@app.route('/backend_endpoint', methods=['POST'])
def backend_endpoint():
    global backend_variable
    msg = request.get_json()

    backend_variable = str(msg)

    return Response('ok', status=200)


def run():
    load_dotenv()
    cert, pkey = (os.getenv("CERT_FILE"),
                  os.getenv("PKEY_FILE")
                  )
    if (cert is None) or (pkey is None):
        print("Running without Https in DEBUG mode...")
        app.run(debug=True,
                host=os.getenv("HOST"),
                port=int(os.getenv("PORT"))
                )
    else:
        print("Running with Https (no DEBUG mode)...")
        app.run(debug=False,
                host=os.getenv("HOST"),
                port=int(os.getenv("PORT")),
                ssl_context=(cert, pkey)
                )


if __name__ == '__main__':
    run()
