import configparser
import threading
import time
from datetime import datetime
import psycopg2
import telebot
from psycopg2 import pool
from telebot import types
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


def create_notification_table():
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS notifications (
                user_id INTEGER NOT NULL,
                notify_time TIME,
                enabled BOOLEAN NOT NULL,
                CONSTRAINT user_id_unique UNIQUE (user_id))""")
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
    set_notify_value(message.chat.id, False)
    keyboard = types.ReplyKeyboardMarkup(row_width=3)
    btn_get = types.KeyboardButton('/get')
    btn_ntf = types.KeyboardButton('/notify')
    btn_del = types.KeyboardButton('/delete')
    keyboard.add(btn_ntf, btn_get, btn_del)
    bot.send_message(message.chat.id, "Input information or click on buttons.", reply_markup=keyboard)


@bot.message_handler(commands=['delete'])
def delete(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("Clear data", callback_data="delete_all"),
                 InlineKeyboardButton("Delete last record", callback_data="delete_last"))
    bot.send_message(message.chat.id, "Delete all information or last record?", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete"))
def handle_callback_query(call):
    user_id = call.from_user.id
    dates = get_saved_dates(user_id)
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
                                          '\nSystolic | Diastolic | Pulse. '
                                          '\nExample: "120 80 60"')
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
                bot.send_message(message.chat.id, 'Incorrect values. \nPlease, try again.')
        except ValueError:
            bot.send_message(message.chat.id, 'Invalid input. \nPlease enter numeric values.')
    connection_pool.putconn(conn)


@bot.message_handler(commands=['get'])
def get_command_handler(message):
    user_id = message.from_user.id
    dates = get_saved_dates(user_id)
    if dates:
        keyboard = telebot.types.InlineKeyboardMarkup()
        for datestr in dates:
            button = telebot.types.InlineKeyboardButton(text=datestr, callback_data=f"date_{datestr}")
            keyboard.add(button)
        bot.send_message(message.chat.id, "Choose a date:", reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, "No saved data found.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("date_"))
def get_handler(call):
    selected_date = call.data[5:]
    user_id = call.from_user.id
    dates = get_saved_dates(user_id)
    if dates:
        for datestr in dates:
            if selected_date == datestr:
                data = get_saved_data(user_id, datestr)
                if data:
                    response = f"Data saved on {datestr}:\n"
                    for row in data:
                        response += f"Time: *{row[3]}* | SBP: *{row[0]}* | DBP: *{row[1]}* | P: *{row[2]}*\n"
                    bot.send_message(call.message.chat.id, response, parse_mode="Markdown")
                else:
                    bot.send_message(call.message.chat.id, "No data found for the selected date.")


def delete_data_by_user_id(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_input WHERE user_id = %s', (user_id,))
    conn.commit()
    connection_pool.putconn(conn)


def delete_last_data_by_user_id(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_input WHERE user_id = %s ORDER BY  DESC LIMIT 1', (user_id,))
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


@bot.message_handler(commands=['notify'])
def notify_handler(message):
    keyboard = types.InlineKeyboardMarkup()
    button_enable = types.InlineKeyboardButton('Enable', callback_data='enable')
    button_disable = types.InlineKeyboardButton('Disable', callback_data='disable')
    keyboard.add(button_enable, button_disable)
    bot.send_message(message.chat.id, "Enable or disable notifications:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data == 'enable')
def enable_handler(call):
    bot.send_message(call.message.chat.id, "Enter time in format \"HH:MM\"")
    bot.register_next_step_handler(call.message, set_notify_time)
    set_notify_value(call.message.chat.id, True)


@bot.callback_query_handler(func=lambda call: call.data == 'disable')
def disable_handler(call):
    set_notify_value(call.message.chat.id, False)
    bot.send_message(call.message.chat.id, "Notification disabled.")


def set_notify_time(message):
    try:
        notify_time = datetime.strptime(message.text, "%H:%M").time()
        set_notify_time_db(message.chat.id, notify_time)
        bot.send_message(message.chat.id, "Notifications enabled at: " + message.text)
    except ValueError:
        bot.send_message(message.chat.id, "Incorrect time format, try again.")
        bot.register_next_step_handler(message, set_notify_time)


def send_notification(user_id, notify_time):
    current_time = str(datetime.now().time())
    if current_time[:5] == notify_time[:5]:
        bot.send_message(user_id, "Check your arterial pressure!")


def get_notify_value(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute("SELECT enabled FROM notifications WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    connection_pool.putconn(conn)
    if result is None:
        return False
    else:
        return bool(result[0])


def set_notify_value(user_id, value):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO notifications (user_id, notify_time, enabled) VALUES (%s, %s, %s) ON CONFLICT (user_id) "
        "DO UPDATE SET notify_time = EXCLUDED.notify_time, enabled = EXCLUDED.enabled", (user_id, None, value))
    conn.commit()
    connection_pool.putconn(conn)


def set_notify_time_db(user_id, notify_time):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO notifications (user_id, notify_time, enabled) VALUES (%s, %s, %s) "
                   "ON CONFLICT (user_id) DO UPDATE SET notify_time = EXCLUDED.notify_time, enabled = EXCLUDED.enabled",
                   (user_id, notify_time.strftime("%H:%M"), True))
    conn.commit()
    connection_pool.putconn(conn)


def notify_loop():
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, notify_time FROM notifications WHERE enabled=True")
    results = cursor.fetchall()
    for result in results:
        user_id, notify_time = result
        notify_time = datetime.strptime(str(notify_time)[:5], "%H:%M").time()
        notify_time = str(notify_time)[:5]
        send_notification(user_id, notify_time)
    connection_pool.putconn(conn)


create_table()
create_notification_table()


def run_notify_loop():
    while True:
        notify_loop()
        time.sleep(60)


thread = threading.Thread(target=run_notify_loop)
thread.start()

bot.polling()
