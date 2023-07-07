import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask
from flask import Response
from flask import request

import logging


def create_connection():
    db_file = f"{get_persistent_folder()}/db.sqlite"
    os.makedirs(get_persistent_folder(), exist_ok=True)
    con = sqlite3.connect(db_file)
    cur = con.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS UserInfo (
        Id INTEGER PRIMARY KEY,
        PendingTripRequests TEXT,
        Username TEXT
    )''')

    con.commit()
    con.close()

    """ create a database connection to a SQLite database """
    return sqlite3.connect(db_file)


class User:
    def __init__(self, user_id, pending_trip_requests, username):
        self.user_id: int = user_id
        self.username: str = username

        # array of {trip_id:int, sender_id: int}
        self.pending_trip_requests: list[dict[any]] = pending_trip_requests

    @staticmethod
    def get_user_by_id(user_id):
        connection = create_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT * FROM UserInfo WHERE Id = ?", (user_id,))
        user_data = cursor.fetchone()

        connection.close()

        if user_data:
            user_id, pending_trip_requests, username = user_data
            # Deserialize pending_trip_requests from JSON string to Python list
            pending_trip_requests = json.loads(pending_trip_requests)
            return User(user_id, pending_trip_requests, username)
        else:
            return None

    def write_back(self):
        connection = create_connection()
        cursor = connection.cursor()

        # Serialize pending_trip_requests from Python list to JSON string
        pending_trip_requests = json.dumps(self.pending_trip_requests)

        cursor.execute("UPDATE UserInfo SET PendingTripRequests = ?, Username = ? WHERE Id = ?",
                       (pending_trip_requests, self.username, self.user_id))

        connection.commit()
        connection.close()


@dataclass
class JoinRequest:
    trip_admin_id: int
    secret_token: str
    trip_id: int
    id_of_person_asking_to_join: int

    @staticmethod
    def from_dict(obj: Any) -> 'JoinRequest':
        _tripAdminId = int(obj.get("trip_admin_id"))
        _secretToken = str(obj.get("secret_token"))
        _tripId = int(obj.get("trip_id"))
        _IdOfPersonAskingToJoin = int(obj.get("id_of_person_asking_to_join"))
        return JoinRequest(_tripAdminId, _secretToken, _tripId, _IdOfPersonAskingToJoin)

    @staticmethod
    def from_json_string(json_str: str) -> 'JoinRequest':
        json_obj = json.loads(json_str)
        return JoinRequest.from_dict(json_obj)


app: Flask = Flask(__name__)
backend_variable: None | str = None


def get_tg_token() -> str:
    return os.getenv("TG_BOT_TOKEN")


def get_tg_secret_token() -> str:
    return os.getenv("TG_SECRET_TOKEN")


def get_backend_secret_token() -> str:
    return os.getenv("BACKEND_SECRET_TOKEN")


def get_persistent_folder() -> str:
    return os.getenv("PERSISTENT_FOLDER")


class TelegramUpdate:
    def __init__(self, user_id, username):
        self.user_id = user_id
        self.username = username


class TextMessageUpdate(TelegramUpdate):
    def __init__(self, user_id, username, text):
        super().__init__(user_id, username)
        self.text = text


class ButtonPressedUpdate(TelegramUpdate):
    def __init__(self, user_id, username, data):
        super().__init__(user_id, username)
        self.data: str = data


def parse_message(message):
    if 'message' in message:
        # Type 1: Text message
        user_id = message['message']['from']['id']
        username = message['message']['from']['username']
        text = message['message']['text']
        return TextMessageUpdate(user_id, username, text)
    elif 'callback_query' in message:
        # Type 2: Button pressed
        user_id = message['callback_query']['from']['id']
        username = message['callback_query']['from']['username']
        data = message['callback_query']['data']
        return ButtonPressedUpdate(user_id, username, data)
    return None


def actualize_and_get_user(update: TelegramUpdate) -> User:
    # Insert or update data in the UserInfo table
    connection = create_connection()
    cursor = connection.cursor()
    # Check if user already exists in the table
    cursor.execute("SELECT * FROM UserInfo WHERE Id = ?", (update.user_id,))
    existing_user = cursor.fetchone()

    if existing_user:
        # User exists, update their information
        cursor.execute("UPDATE UserInfo SET Username = ? WHERE Id = ?", (update.username, update.user_id))
    else:
        # User doesn't exist, insert a new row
        cursor.execute("INSERT INTO UserInfo (Username, Id, PendingTripRequests) VALUES (?, ?, ?)",
                       (update.user_id, update.user_id, "[]"))
    cursor.close()
    connection.commit()
    connection.close()

    return User.get_user_by_id(update.user_id)


def handle_tg_update(update):
    if isinstance(update, TextMessageUpdate):
        # Probably the first message, "/start"
        user = actualize_and_get_user(update)
    elif isinstance(update, ButtonPressedUpdate):
        answering_user = actualize_and_get_user(update)
        answer_parts = update.data.split('_')
        answer = answer_parts[0]
        trip_id = int(answer_parts[1])
        id_of_person_asking_to_join = int(answer_parts[2])

        matching_pending_request_index: int | None = None
        for i, request in enumerate(answering_user.pending_trip_requests, 0):
            if (request['trip_id'] == trip_id) and (request['sender_id'] == id_of_person_asking_to_join):
                matching_pending_request_index = i
                break

        if matching_pending_request_index is None:
            logging.error(
                f"No matching requests found! tripId {trip_id}, sender_id {id_of_person_asking_to_join}, tripAdminId {answering_user.user_id}")

        message_id = answering_user.pending_trip_requests[matching_pending_request_index]['message_id']
        answering_user.pending_trip_requests.pop(matching_pending_request_index)
        answering_user.write_back()

        tg_remove_message(answering_user.user_id, message_id)
        tg_send_message(id_of_person_asking_to_join,
                        "You have been accepted" if answer == 'y' else "You have been rejected")


def tg_remove_message(chat_id, message_id):
    url = f'https://api.telegram.org/bot{get_tg_token()}/deleteMessage'
    payload = {
        "chat_id": chat_id,
        "message_id": message_id
    }

    response = requests.post(url, json=payload)

    logging.info(f"Response for tg_remove_message: '{response.text}'")


def tg_send_join_request(chat_id, asker_username, data_to_imbue):
    url = f'https://api.telegram.org/bot{get_tg_token()}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': f"[@{asker_username}](https://t.me/{asker_username}) asks to join your trip",  # TODO: info about trip
        "parse_mode": "MarkdownV2",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "Accept",
                        "callback_data": f"y_{data_to_imbue}"
                    },
                    {
                        "text": "Refuse",
                        "callback_data": f"n_{data_to_imbue}"
                    }
                ]
            ]
        }
    }

    response = requests.post(url, json=payload)

    logging.info(f"Response for tg_send_join_request: '{response.text}'")

    return json.loads(response.text)['result']['message_id']


def tg_send_message(chat_id, text):
    url = f'https://api.telegram.org/bot{get_tg_token()}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
    }

    response = requests.post(url, json=payload)

    logging.info(f"Response for tg_send_message: '{response.text}'")


@app.route('/telegram_endpoint', methods=['POST'])
def telegram_endpoint():
    token_received = request.headers.get('X-Telegram-Bot-Api-Secret-Token', 'no-key')
    if get_tg_secret_token() != token_received:
        logging.error(f"Unauthorized! Tried to access with token {token_received}'")
        return Response(status=403)

    logging.info(f"Telegram endpoint request json is '{request.get_json()}'")
    msg = request.get_json()
    parsed_message = parse_message(msg)
    if parsed_message is None:
        # Some kind of unhandled message came our way: we lie to Telegram, saying that we handled it
        return Response('ok', status=200)
    try:
        handle_tg_update(parsed_message)
    finally:
        return Response('ok', status=200)


@app.route('/join_request', methods=['POST'])
def backend_endpoint():
    global backend_variable
    msg = request.get_json()
    backend_request = JoinRequest.from_dict(msg)
    if backend_request.secret_token != get_backend_secret_token():
        logging.error(f"Unauthorized! Tried to access with token {backend_request.secret_token}'")
        return Response(status=403)
    user_to_send_to = User.get_user_by_id(backend_request.trip_admin_id)
    sender = User.get_user_by_id(backend_request.id_of_person_asking_to_join)

    message_id = \
        tg_send_join_request(user_to_send_to.user_id, sender.username,
                             f"{backend_request.trip_id}_{backend_request.id_of_person_asking_to_join}")

    user_to_send_to.pending_trip_requests.append(
        {"trip_id": backend_request.trip_id,
         "sender_id": backend_request.id_of_person_asking_to_join,
         "message_id": message_id})
    user_to_send_to.write_back()

    return Response('ok', status=200)


def run():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),  # Log to console
            logging.FileHandler('app.log')  # Log to file
        ]
    )

    load_dotenv()

    cert, pkey = (os.getenv("CERT_FILE"),
                  os.getenv("PKEY_FILE")
                  )
    if (cert is None) or (pkey is None):
        logging.info("Running without Https in DEBUG mode...")
        app.run(debug=True,
                host=os.getenv("HOST"),
                port=int(os.getenv("PORT"))
                )
    else:
        logging.info("Running with Https (no DEBUG mode)...")
        app.run(debug=False,
                host=os.getenv("HOST"),
                port=int(os.getenv("PORT")),
                ssl_context=(cert, pkey)
                )


if __name__ == '__main__':
    run()
