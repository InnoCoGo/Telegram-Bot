import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
from dateutil import tz
from dotenv import load_dotenv
from flask import Flask
from flask import Response
from flask import request

messages = [
    # English
    {
        'trip_ask': "requests to join the trip",
        'rejected': "rejected you for the trip",
        'accepted': "accepted you for the trip",
        'reject': "Reject",
        'accept': "Accept",
        'in_message_at': "at",
        'in_MSK': "(MSK)"
    },
    # Russian
    {
        'trip_ask': "хотят принять участие в вашей поездке",
        'rejected': "отказались принимать вас в поездку",
        'accepted': "приняли вас в поездку",
        'reject': "Отказать",
        'accept': "Принять",
        'in_message_at': "в",
        'in_MSK': "(МСК)"
    }
]

destinations = [
    # English
    {
        "0": "Innopolis",
        "1": "Kazan",
        "2": "Verkhniy Uslon"
    },
    # Russian
    {
        "0": "Иннополис",
        "1": "Казань",
        "2": "Верхний Услон"
    }
]


def create_connection():
    db_file = f"{get_persistent_folder()}/db.sqlite"
    os.makedirs(get_persistent_folder(), exist_ok=True)
    con = sqlite3.connect(db_file)
    cur = con.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS UserInfo (
        Id INTEGER PRIMARY KEY,
        LanguageCode TEXT,
        PendingTripRequests TEXT,
        Username TEXT
    )''')

    con.commit()
    con.close()

    """ create a database connection to a SQLite database """
    return sqlite3.connect(db_file)


class User:
    def get_language_index(self):
        return 1 if self.language_code == 'ru' else 0

    def __init__(self, user_id, language_code, pending_trip_requests, username):
        self.user_id: int = user_id
        self.username: str = username
        self.language_code: str = language_code

        # array of {trip_id:int, sender_id: int, message_id: int, raw_trip_desc: str}
        self.pending_trip_requests: list[dict[any]] = pending_trip_requests

    @staticmethod
    def get_user_by_id(user_id):
        connection = create_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT * FROM UserInfo WHERE Id = ?", (user_id,))
        user_data = cursor.fetchone()

        connection.close()

        if user_data:
            user_id, language_code, pending_trip_requests, username = user_data
            # Deserialize pending_trip_requests from JSON string to Python list
            pending_trip_requests = json.loads(pending_trip_requests)
            return User(user_id, language_code, pending_trip_requests, username)
        else:
            return None

    def write_back(self):
        connection = create_connection()
        cursor = connection.cursor()

        # Serialize pending_trip_requests from Python list to JSON string
        pending_trip_requests = json.dumps(self.pending_trip_requests)

        cursor.execute("UPDATE UserInfo SET PendingTripRequests = ?, LanguageCode = ?, Username = ? WHERE Id = ?",
                       (pending_trip_requests, self.language_code, self.username, self.user_id))

        connection.commit()
        connection.close()


@dataclass
class JoinRequest:
    trip_admin_id: int
    secret_token: str
    trip_id: int
    id_of_person_asking_to_join: int
    tg_id_of_person_asking_to_join: int
    trip_name: str

    @staticmethod
    def from_dict(obj: Any) -> 'JoinRequest':
        _tripAdminId = int(obj.get("trip_admin_tg_id"))
        _secretToken = str(obj.get("secret_token"))
        _tripId = int(obj.get("trip_id"))
        _IdOfPersonAskingToJoin = int(obj.get("id_of_person_asking_to_join"))
        return JoinRequest(_tripAdminId, _secretToken, _tripId, _IdOfPersonAskingToJoin,
                           int(obj.get('tg_id_of_person_asking_to_join')), obj.get('trip_name'))

    @staticmethod
    def from_json_string(json_str: str) -> 'JoinRequest':
        json_obj = json.loads(json_str)
        return JoinRequest.from_dict(json_obj)


def find_and_replace_iso_datetimes_at_the_end_of_line(some_line: str):
    # Works for a thousand years (literally)
    # Get the beginning of ISO string starting with the year, 2***-**-**T**:**:**.**Z
    datetime_start_index = some_line.index('2')
    datetime_original = some_line[datetime_start_index:]

    dt = datetime.strptime(datetime_original, '%Y-%m-%dT%H:%M:%S.%f%z')

    # change timezone to Moscow Standard Time:
    dt = dt.astimezone(tz.gettz('Moscow Standard Time'))
    # datetime.datetime(2020, 5, 23, 12, 5, 11, 418279, tzinfo=tzfile('Asia/Calcutta'))

    # note for Python 3.9+:
    # use zoneinfo from the standard lib to get timezone objects

    # now format to string with desired format
    s_out = dt.strftime('%Y-%m-%d %I:%M %p')
    return some_line.replace(datetime_original, s_out)


def get_translated_trip_name(trip_name: str, langauge_index: int):
    localized_trip_name = trip_name
    localized_destinations = destinations[langauge_index]
    num1 = trip_name[0]
    num2 = trip_name[5]
    localized_trip_name = localized_trip_name.replace(num1, localized_destinations[num1], 1) \
        .replace(num2, localized_destinations[num2], 1)
    return (find_and_replace_iso_datetimes_at_the_end_of_line(localized_trip_name) + " " + messages[langauge_index]['in_MSK'])\
        .replace('at:', messages[langauge_index]['in_message_at']) \
        .replace('-', '\\-').replace('>', '\\>').replace('.', '\\.').replace('(', '\\(').replace(')', '\\)')


app: Flask = Flask(__name__)
backend_variable: None | str = None


def get_tg_token() -> str:
    return os.getenv("TG_BOT_TOKEN")


def get_tg_secret_token() -> str:
    return os.getenv("TG_SECRET_TOKEN")


def get_backend_secret_token() -> str:
    return os.getenv("BACKEND_SECRET_TOKEN")


def get_backend_url() -> str:
    return os.getenv("BACKEND_URL")


def get_persistent_folder() -> str:
    return os.getenv("PERSISTENT_FOLDER")


class TelegramUpdate:
    def __init__(self, user_id, username, language_code):
        self.user_id = user_id
        self.username = username
        self.language_code = language_code


class TextMessageUpdate(TelegramUpdate):
    def __init__(self, user_id, username, text, language_code):
        super().__init__(user_id, username, language_code)
        self.text = text


class ButtonPressedUpdate(TelegramUpdate):
    def __init__(self, user_id, username, data, language_code):
        super().__init__(user_id, username, language_code)
        self.data: str = data


def parse_message(message):
    if 'message' in message:
        # Type 1: Text message
        user_id = message['message']['from']['id']
        username = message['message']['from']['username']
        langauge_code = message['message']['from']['language_code']
        text = message['message']['text']
        return TextMessageUpdate(user_id, username, text, langauge_code)
    elif 'callback_query' in message:
        # Type 2: Button pressed
        user_id = message['callback_query']['from']['id']
        username = message['callback_query']['from']['username']
        langauge_code = message['callback_query']['from']['language_code']
        data = message['callback_query']['data']
        return ButtonPressedUpdate(user_id, username, data, langauge_code)
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
        cursor.execute("UPDATE UserInfo SET Username = ?, LanguageCode = ? WHERE Id = ?",
                       (update.username, update.language_code, update.user_id))
    else:
        # User doesn't exist, insert a new row
        cursor.execute("INSERT INTO UserInfo (Username, Id, PendingTripRequests, LanguageCode) VALUES (?, ?, ?, ?)",
                       (update.username, update.user_id, "[]", update.language_code))
    cursor.close()
    connection.commit()
    connection.close()

    return User.get_user_by_id(update.user_id)


def create_accepted_message(user_receiving_message: User, user_who_accepted: User, trip_desc: str):
    language_index = user_receiving_message.get_language_index()
    # TODO: get info about trip from backend?
    return f"[@{user_who_accepted.username}](https://t.me/{user_who_accepted.username}) " + \
        messages[language_index]['accepted'] + " " + get_translated_trip_name(trip_desc, language_index)


def create_rejected_message(user_receiving_message: User, user_who_accepted: User, trip_desc: str):
    language_index = user_receiving_message.get_language_index()
    # TODO: get info about trip from backend?
    return f"[@{user_who_accepted.username}](https://t.me/{user_who_accepted.username}) " + \
        messages[language_index]['rejected'] + " " + get_translated_trip_name(trip_desc, language_index)


def handle_tg_update(update):
    if isinstance(update, TextMessageUpdate):
        # Probably the first message, "/start"
        actualize_and_get_user(update)
    elif isinstance(update, ButtonPressedUpdate):
        answering_user = actualize_and_get_user(update)
        answer_parts = update.data.split('_')
        answer = answer_parts[0]
        trip_id = int(answer_parts[1])
        id_of_person_asking_to_join = int(answer_parts[2])
        internal_id_of_person_asking_to_join = int(answer_parts[3])

        matching_pending_request_index: int | None = None
        for i, pending_request in enumerate(answering_user.pending_trip_requests, 0):
            if (pending_request['trip_id'] == trip_id) and (
                    pending_request['sender_id'] == id_of_person_asking_to_join):
                matching_pending_request_index = i
                break

        if matching_pending_request_index is None:
            logging.error(
                f"No matching requests found! tripId {trip_id}, sender_id {id_of_person_asking_to_join}, tripAdminId {answering_user.user_id}")

        asking_user = User.get_user_by_id(id_of_person_asking_to_join)
        message_id = answering_user.pending_trip_requests[matching_pending_request_index]['message_id']
        raw_trip_desc = answering_user.pending_trip_requests[matching_pending_request_index]['raw_trip_desc']
        answering_user.pending_trip_requests.pop(matching_pending_request_index)
        answering_user.write_back()

        tg_remove_message(answering_user.user_id, message_id)
        tg_send_message(id_of_person_asking_to_join,
                        create_accepted_message(asking_user, answering_user, raw_trip_desc) if answer == 'y'
                        else create_rejected_message(asking_user, answering_user, raw_trip_desc))

        url = f'{get_backend_url()}/api/v1/user/join_trip/res'
        payload = {
            'trip_id': trip_id,
            'id_of_person_asking_to_join': internal_id_of_person_asking_to_join,
            'secret_token': get_backend_secret_token(),
            'accepted': answer == 'y'
        }
        logging.info(f"Sending data to server: {payload}")

        response = requests.post(url, json=payload)

        logging.info(f"Response from server: '{response.text}'")


def tg_remove_message(chat_id, message_id):
    url = f'https://api.telegram.org/bot{get_tg_token()}/deleteMessage'
    payload = {
        "chat_id": chat_id,
        "message_id": message_id
    }

    response = requests.post(url, json=payload)

    logging.info(f"Response for tg_remove_message: '{response.text}'")


def tg_send_join_request(chat_id, asker_username, data_to_imbue, language_index, trip_desc: str):
    url = f'https://api.telegram.org/bot{get_tg_token()}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': f"[@{asker_username}](https://t.me/{asker_username}) {messages[language_index]['trip_ask']} {get_translated_trip_name(trip_desc, language_index)}",
        # TODO: info about trip
        "parse_mode": "MarkdownV2",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": messages[language_index]['accept'],
                        "callback_data": f"y_{data_to_imbue}"
                    },
                    {
                        "text": messages[language_index]['reject'],
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
        "parse_mode": "MarkdownV2",

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

    try:
        parsed_message = parse_message(msg)
        handle_tg_update(parsed_message)
    except Exception as e:
        logging.error(e)
    finally:
        # Some kind of unhandled message came our way: we lie to Telegram, saying that we handled it
        return Response('ok', status=200)


@app.route('/join_request', methods=['POST'])
def backend_endpoint():
    global backend_variable
    msg = request.get_json()
    logging.info(f"receiving message from backend: {msg}")
    backend_request = JoinRequest.from_dict(msg)
    if backend_request.secret_token != get_backend_secret_token():
        logging.error(f"Unauthorized! Tried to access with token {backend_request.secret_token}'")
        return Response(status=403)
    user_to_send_to = User.get_user_by_id(backend_request.trip_admin_id)
    sender = User.get_user_by_id(backend_request.tg_id_of_person_asking_to_join)

    matching_pending_request_index: int | None = None
    for i, pending_request in enumerate(user_to_send_to.pending_trip_requests, 0):
        if (pending_request['trip_id'] == backend_request.trip_id) and (
                pending_request['sender_id'] == backend_request.tg_id_of_person_asking_to_join):
            matching_pending_request_index = i
            break

    if matching_pending_request_index is not None:
        logging.error(
            f"Matching request already found! tripId {backend_request.trip_id}, sender_id {backend_request.tg_id_of_person_asking_to_join}, tripAdminId {backend_request.trip_admin_id}")
        return Response('ok', status=200)

    message_id = \
        tg_send_join_request(user_to_send_to.user_id, sender.username,
                             f"{backend_request.trip_id}_{backend_request.tg_id_of_person_asking_to_join}_{backend_request.id_of_person_asking_to_join}",
                             user_to_send_to.get_language_index(), backend_request.trip_name)

    user_to_send_to.pending_trip_requests.append(
        {"trip_id": backend_request.trip_id,
         "sender_id": backend_request.tg_id_of_person_asking_to_join,
         'raw_trip_desc': backend_request.trip_name,
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
