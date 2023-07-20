import configparser
from datetime import datetime
import psycopg2
import telebot
from psycopg2 import pool
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

config = configparser.ConfigParser()
config.read('config.ini')

connection_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=config.get('DB', 'minconn'),
    maxconn=config.get('DB', 'maxconn'),
    host=config.get('DB', 'host'),
    port=config.get('DB', 'port'),
    database=config.get('DB', 'database'),
    user=config.get('DB', 'user'),
    password=config.get('DB', 'password')
)
bot = telebot.TeleBot(config.get('TG', 'token'))


def create_table():
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_input
                      (user_id INTEGER, systolic INTEGER, diastolic INTEGER, pulse INTEGER, date TEXT, time TEXT)''')
    conn.commit()
    connection_pool.putconn(conn)


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id,
                     "Arterial pressure monitoring enabled! \nTo start please enter three values separated by spaces. "
                     "\nSystolic | Diastolic | Pulse. "
                     "\nExample: \"120 80 60\" \n--- "
                     "\nAvailable commands: "
                     "\n/get - get information by date "
                     "\n/delete - clear your data")


@bot.message_handler(commands=['delete'])
def delete(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("Clear data", callback_data="delete_all"),
                 InlineKeyboardButton("Delete last record", callback_data="delete_last"))
    bot.send_message(message.chat.id, "Delete all information or last record?", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    dates = get_saved_dates(user_id)
    if dates:
        for datestr in dates:
            if call.data == datestr:
                data = get_saved_data(user_id, datestr)
                if data:
                    response = f"Data saved on {datestr}:\n"
                    for row in data:
                        response += f"Time: *{row[3]}* | SBP: *{row[0]}* | DBP: *{row[1]}* | P: *{row[2]}*\n"
                    bot.send_message(call.message.chat.id, response, parse_mode="Markdown")
                else:
                    bot.send_message(call.message.chat.id, "No data found for the selected date.")
    else:
        match call.data:
            case "delete_all":
                if not dates:
                    bot.send_message(call.message.chat.id, "No saved data found.")
                else:
                    keyboard = InlineKeyboardMarkup()
                    keyboard.row(InlineKeyboardButton("Yes", callback_data="delete_all_yes"),
                                 InlineKeyboardButton("No", callback_data="delete_all_no"))
                    bot.send_message(call.message.chat.id, "Are you sure? \nALL saved information will be lost!",
                                     reply_markup=keyboard)
            case "delete_all_yes":
                delete_data_by_user_id(user_id=call.message.chat.id)
                bot.send_message(chat_id=call.message.chat.id, text="Data cleared.")
            case "delete_all_no":
                bot.send_message(chat_id=call.message.chat.id, text="Deletion canceled.")
            case "delete_last":
                if not dates:
                    bot.send_message(call.message.chat.id, "No saved data found.")
                else:
                    delete_last_data_by_user_id(user_id=call.message.chat.id)


@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/'))
def handle_text(message):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    input_values = message.text.split()
    if len(input_values) != 3:
        bot.send_message(message.chat.id, 'Please enter three values separated by spaces. '
                                          '\n Systolic | Diastolic | Pulse. '
                                          '\n Example: "120 80 60"')
    else:
        try:
            user_id = message.from_user.id
            systolic, diastolic, pulse = map(int, input_values)
            if 0 <= systolic <= 300 and 0 <= diastolic <= 300 and 0 <= pulse <= 300:
                current_date = datetime.now().strftime('%d-%m-%Y')
                current_time = datetime.now().strftime("%H:%M")
                cursor.execute('INSERT INTO user_input VALUES (%s, %s, %s, %s, %s, %s)',
                               (user_id, systolic, diastolic, pulse, current_date, current_time))
                conn.commit()
                bot.send_message(message.chat.id, 'Information saved successfully.')
            else:
                bot.send_message(message.chat.id, 'Incorrect values. \n Please, try again.')
        except ValueError:
            bot.send_message(message.chat.id, 'Invalid input. \n Please enter numeric values.')
    connection_pool.putconn(conn)


@bot.message_handler(commands=['get'])
def get_command_handler(message):
    user_id = message.from_user.id
    dates = get_saved_dates(user_id)
    if dates:
        keyboard = telebot.types.InlineKeyboardMarkup()
        for datestr in dates:
            button = telebot.types.InlineKeyboardButton(text=datestr, callback_data=datestr)
            keyboard.add(button)
        bot.send_message(message.chat.id, "Choose a date:", reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, "No saved data found.")


def delete_data_by_user_id(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_input WHERE user_id = %s', (user_id,))
    conn.commit()
    connection_pool.putconn(conn)


def delete_last_data_by_user_id(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_input WHERE user_id = %s ORDER BY id DESC LIMIT 1', (user_id,))
    conn.commit()
    connection_pool.putconn(conn)


def get_saved_dates(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT date FROM user_input WHERE user_id = %s', (user_id,))
    dates = [row[0] for row in cursor.fetchall()]
    connection_pool.putconn(conn)
    return dates


def get_saved_data(user_id, selected_date):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('SELECT systolic, diastolic, pulse, time FROM user_input WHERE user_id = %s AND date = %s',
                   (user_id, selected_date))
    data = cursor.fetchall()
    connection_pool.putconn(conn)
    return data


create_table()
bot.polling()
