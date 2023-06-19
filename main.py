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
    msg = request.get_json()

    parsed_message = parse_message(msg)
    if parsed_message is None:
        # Some kind of unhandled message came our way: we lie to Telegram, saying that we handled it
        return Response('ok', status=200)
    chat_id,text = parsed_message
    handle_tg_update(chat_id, text)

    return Response('ok', status=200)


@app.route('/backend_endpoint', methods=['POST'])
def backend_endpoint():
    global backend_variable
    msg = request.get_json()

    backend_variable = str(msg)

    return Response('ok', status=200)


if __name__ == '__main__':
    load_dotenv()
    app.run(debug=True, host=os.getenv("HOST"), port=int(os.getenv("PORT")), ssl_context=(os.getenv("CERT_FILE"), os.getenv("PKEY_FILE")))
