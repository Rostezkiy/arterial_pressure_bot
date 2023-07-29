import configparser
import logging
import threading
import time
from datetime import datetime
from io import BytesIO
import psycopg2
import telebot
from matplotlib import pyplot as plt
from psycopg2 import pool, sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.debug("Starting application.")
config = configparser.ConfigParser()
config.read('config.ini')
bot = telebot.TeleBot(config.get('TG', 'token'))
logging.debug("Configuration done.")


def connect_to_db():
    database = config.get('DB', 'database')
    conn = psycopg2.connect(dbname='postgres', user='postgres', password='postgres', host=config.get('DB', 'host'),
                            port=config.get('DB', 'port'))
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    cursor = conn.cursor()
    # Check if database exists and create it if not
    cursor.execute("SELECT datname FROM pg_database;")
    list_database = [item[0] for item in cursor.fetchall()]
    if database not in list_database:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        logging.debug("Creating DB.")
    else:
        logging.debug("DB already created.")
    cursor.close()
    conn.close()

    # Reconnecting to the new database
    conn = psycopg2.connect(host=config.get('DB', 'host'),
                            port=config.get('DB', 'port'),
                            dbname=config.get('DB', 'database'),
                            user=config.get('DB', 'user'),
                            password=config.get('DB', 'password'))
    return conn


connect_to_db()

connection_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=config.get('DB', 'minconn'),
    maxconn=config.get('DB', 'maxconn'),
    host=config.get('DB', 'host'),
    port=config.get('DB', 'port'),
    database=config.get('DB', 'database'),
    user=config.get('DB', 'user'),
    password=config.get('DB', 'password')
)


def create_table():
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_input(
        id SERIAL PRIMARY KEY,
        user_id INTEGER, 
        systolic INTEGER, 
        diastolic INTEGER, 
        pulse INTEGER, 
        date TEXT, 
        time TEXT)''')
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
    start_app(message)


@bot.message_handler(commands=['delete'])
def delete(message):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("Clear data", callback_data="delete_all"),
                 InlineKeyboardButton("Delete last record", callback_data="delete_last"))
    bot.send_message(message.chat.id, "Delete all information or last record?", reply_markup=keyboard)


@bot.message_handler(commands=['help'])
def help_message(message):
    bot.send_message(message.chat.id,
                     "Arterial Pressure Monitoring.\nTo start please enter three values separated by spaces. "
                     "\nSystolic | Diastolic | Pulse. "
                     "\nExample: \"120 80 60\" \n--- "
                     "\nAvailable commands:"
                     "\n/help -- view help information"
                     "\n/get -- get information by date"
                     "\n/graph -- get graph based on your information"
                     "\n/notify -- configure notification"
                     "\n/reset -- click this "
                     "if you need to reload keyboard buttons"
                     "\n/delete -- clear your data")
    reload(message)


@bot.message_handler(commands=['reset'])
def reset(message):
    reload(message)


def start_app(message):
    bot.send_message(message.chat.id,
                     "Arterial Pressure Monitoring.\nTo start please enter three values separated by spaces. "
                     "\nSystolic | Diastolic | Pulse. "
                     "\nExample: \"120 80 60\" \n--- "
                     "\nAvailable commands:"
                     "\n/help -- view help information"
                     "\n/get -- get information by date"
                     "\n/graph -- get graph based on your information"
                     "\n/notify -- configure notification"
                     "\n/reset -- click this "
                     "if you need to reload keyboard buttons"
                     "\n/delete -- clear your data")
    set_notify_value(message.chat.id, False)
    logging.debug(f"User {message.chat.id} activated bot.")
    reload(message)


def reload(message):
    btn_get = types.KeyboardButton('/get')
    btn_graph = types.KeyboardButton('/graph')
    btn_ntf = types.KeyboardButton('/notify')
    btn_del = types.KeyboardButton('/delete')
    keyboard = types.ReplyKeyboardMarkup(row_width=2)
    keyboard.add(btn_ntf, btn_del, btn_get, btn_graph)
    bot.send_message(message.chat.id, "Input information or click on buttons.", reply_markup=keyboard)


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
                bot.send_message(call.message.chat.id, "Last record removed.")


@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/'))
def handle_text(message):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    input_values = message.text.split()
    if len(input_values) != 3:
        bot.send_message(message.chat.id, 'Please enter 3 values separated by spaces. '
                                          '\nSystolic | Diastolic | Pulse. '
                                          '\nExample: "120 80 60"')
    else:
        try:
            user_id = message.from_user.id
            systolic, diastolic, pulse = map(int, input_values)
            if 0 <= systolic <= 300 and 0 <= diastolic <= 300 and 0 <= pulse <= 300:
                current_date = datetime.now().strftime('%d-%m-%Y')
                current_time = datetime.now().strftime("%H:%M")
                cursor.execute('INSERT INTO user_input (user_id, systolic, diastolic, pulse, date, time) '
                               'VALUES (%s, %s, %s, %s, %s, %s)',
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
    if not dates:
        bot.send_message(message.chat.id, "No saved data found.")
    else:
        year_set = set()
        for date in dates:
            dt = datetime.strptime(date, '%d-%m-%Y')
            year = dt.year
            year_set.add(year)
        keyboard = telebot.types.InlineKeyboardMarkup()
        for year in year_set:
            button = telebot.types.InlineKeyboardButton(text=year, callback_data=f"year_text_{year}")
            keyboard.add(button)
        bot.send_message(message.chat.id, "Select year:", reply_markup=keyboard)


@bot.message_handler(commands=['graph'])
def graph_command_handler(message):
    user_id = message.from_user.id
    dates = get_saved_dates(user_id)
    if not dates:
        bot.send_message(message.chat.id, "No saved data found.")
    else:
        year_set = set()
        for date in dates:
            dt = datetime.strptime(date, '%d-%m-%Y')
            year = dt.year
            year_set.add(year)
        keyboard = telebot.types.InlineKeyboardMarkup()
        for year in year_set:
            button = telebot.types.InlineKeyboardButton(text=year, callback_data=f"year_{year}")
            keyboard.add(button)
        bot.send_message(message.chat.id, "Select year:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("year_text_"))
def handle_year_selection(call):
    user_id = call.message.chat.id
    months = set()
    for month in get_saved_dates(user_id):
        dt = datetime.strptime(month, '%d-%m-%Y')
        month = dt.strftime('%m')
        months.add(month)
    sorted_months = sorted(months)
    keyboard = telebot.types.InlineKeyboardMarkup()
    for month in sorted_months:
        button = telebot.types.InlineKeyboardButton(text=month, callback_data=f"month_text_{month}-{call.data[10:]}")
        keyboard.add(button)
    bot.send_message(chat_id=call.message.chat.id, text="Select a month:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("draw_year_"))
def handle_year_selection(call):
    user_id = call.message.chat.id
    months = set()
    for month in get_saved_dates(user_id):
        dt = datetime.strptime(month, '%d-%m-%Y')
        month = dt.strftime('%m')
        months.add(month)
    sorted_months = sorted(months)
    keyboard = telebot.types.InlineKeyboardMarkup()
    for month in sorted_months:
        button = telebot.types.InlineKeyboardButton(text=month, callback_data=f"month_{month}-{call.data[10:]}")
        keyboard.add(button)
    bot.send_message(chat_id=call.message.chat.id, text="Select a month:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("month_text_"))
def handle_month_selection(call):
    user_id = call.message.chat.id
    days = set()
    month = "%" + call.data[11:]
    for day in get_saved_days(user_id, month):
        dt = datetime.strptime(day, '%d-%m-%Y')
        day = dt.strftime('%d')
        days.add(day)
    sorted_days = sorted(days)
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=4)
    for i in range(0, len(sorted_days), 5):
        row = sorted_days[i:i + 5]
        button = [telebot.types.InlineKeyboardButton(text=str(day),
                                                     callback_data=f"text_{day}-{call.data[11:]}") for day in row]
        keyboard.row(*button)
    bot.send_message(chat_id=call.message.chat.id, text="Select a day:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("draw_days_"))
def handle_month_selection(call):
    user_id = call.message.chat.id
    days = set()
    month = "%" + call.data[10:]
    for day in get_saved_days(user_id, month):
        dt = datetime.strptime(day, '%d-%m-%Y')
        day = dt.strftime('%d')
        days.add(day)
    sorted_days = sorted(days)
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=4)
    for i in range(0, len(sorted_days), 5):
        row = sorted_days[i:i + 5]
        button = [telebot.types.InlineKeyboardButton(text=str(day),
                                                     callback_data=f"pict_{day}-{call.data[10:]}") for day in row]
        keyboard.row(*button)
    bot.send_message(chat_id=call.message.chat.id, text="Select a day:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("day_"))
def handle_text_or_graph_selection(call):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("Text", callback_data=f"text_{call.data[4:]}"),
                 InlineKeyboardButton("Graph", callback_data=f"pict_{call.data[4:]}"))
    bot.send_message(call.message.chat.id, "Text or Graph", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("month_"))
def handle_text_or_graph_selection(call):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("Select day", callback_data=f"draw_days_{call.data[6:]}"),
                 InlineKeyboardButton("Graph ", callback_data=f"draw_month_{call.data[6:]}"))
    bot.send_message(call.message.chat.id, "Select day or Monthly graph", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("year_"))
def handle_text_or_graph_selection(call):
    keyboard = InlineKeyboardMarkup()
    keyboard.row(InlineKeyboardButton("Select month", callback_data=f"draw_year_{call.data[5:]}"),
                 InlineKeyboardButton("Graph", callback_data="graph_sum"))
    bot.send_message(call.message.chat.id, "Select month or Graph for the year", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("text_"))
def handle_day_selection(call):
    user_id = call.message.chat.id
    selected_date = str(call.data[5:])
    data = get_saved_data(user_id, selected_date)
    if not data:
        bot.send_message(call.message.chat.id, "No data found for the selected date.")
    else:
        response = f"Data saved on {call.data[5:]}:\n"
        for row in data:
            response += f"Time: *{row[3]}* | SBP: *{row[0]}* | DBP: *{row[1]}* | P: *{row[2]}*\n"
        bot.send_message(call.message.chat.id, response, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == 'graph_sum')
def handle_generate_graph(call):
    user_id = call.message.chat.id
    select_user_data_by_id(user_id)


def select_user_data_by_id(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_input WHERE user_id=%s", (user_id,))
    rows = cursor.fetchall()
    if len(rows) != 0:
        date = [row[4] for row in rows]
        systolic = [row[1] for row in rows]
        diastolic = [row[2] for row in rows]
        pulse = [row[3] for row in rows]
        plt.figure()
        plt.plot(date, systolic, color='red', label='Systolic')
        plt.plot(date, diastolic, color='blue', label='Diastolic')
        plt.plot(date, pulse, color='green', label='pulse')
        plt.xlabel('Time')
        plt.ylabel('Values')
        plt.title('Arterial Pressure Summary')
        plt.legend()
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        bot.send_photo(chat_id=user_id, photo=buffer)
        buffer.close()
        plt.close()
        cursor.close()
        conn.close()
    else:
        bot.send_message(user_id, "No data found for the selected date.")


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


@bot.callback_query_handler(func=lambda call: call.data.startswith("pict_"))
def graph_handler(call):
    selected_date = call.data[5:]
    user_id = call.from_user.id
    dates = get_saved_dates(user_id)
    if dates:
        for datestr in dates:
            if selected_date == datestr:
                data = get_saved_data(user_id, datestr)
                if data:
                    rows = data
                    x = [row[3] for row in rows]
                    y1 = [row[0] for row in rows]  # systolic bp
                    y2 = [row[1] for row in rows]  # diastolic bp
                    y3 = [row[2] for row in rows]  # pulse
                    plt.plot(x, y1, color='red', label='SBP')
                    plt.plot(x, y2, color='blue', label='DBP')
                    plt.plot(x, y3, color='green', label='Pulse')
                    plt.xlabel('Time')
                    plt.ylabel('Values')
                    plt.title('Arterial Pressure')
                    plt.legend()
                    buffer = BytesIO()
                    plt.savefig(buffer, format='png')
                    buffer.seek(0)
                    bot.send_photo(chat_id=call.message.chat.id, photo=buffer)
                    buffer.close()
                    plt.close()
                else:
                    bot.send_message(call.message.chat.id, "No data found for the selected date.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("draw_month_"))
def graph_handler(call):
    format_date = "%" + call.data[11:]
    user_id = call.message.chat.id
    dates = get_saved_days(user_id, format_date)
    if dates:
        data = get_saved_month_data(user_id, format_date)
        if data:
            rows = data
            x = [row[3][:2] for row in rows]
            y1 = [row[0] for row in rows]  # systolic bp
            y2 = [row[1] for row in rows]  # diastolic bp
            y3 = [row[2] for row in rows]  # pulse
            plt.plot(x, y1, color='red', label='SBP')
            plt.plot(x, y2, color='blue', label='DBP')
            plt.plot(x, y3, color='green', label='Pulse')
            plt.xlabel('Date')
            plt.ylabel('Values')
            plt.title('Arterial Pressure')
            plt.legend()
            buffer = BytesIO()
            plt.savefig(buffer, format='png')
            buffer.seek(0)
            bot.send_photo(chat_id=call.message.chat.id, photo=buffer)
            buffer.close()
            plt.close()
        else:
            bot.send_message(call.message.chat.id, "No data found for the selected date.")
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
    query = """
        DELETE FROM user_input
        WHERE id = (
            SELECT MAX(id)
            FROM user_input
            WHERE user_id = %s
        ) AND user_id = %s;
    """
    cursor.execute(query, (user_id, user_id))
    conn.commit()
    connection_pool.putconn(conn)


def get_saved_dates(user_id):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT date FROM user_input WHERE user_id = %s', (user_id,))
    dates = [row[0] for row in cursor.fetchall()]
    connection_pool.putconn(conn)
    return dates


def get_saved_days(user_id, month):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT date FROM user_input WHERE user_id = %s AND date LIKE %s", (user_id, month))
    days = [row[0] for row in cursor.fetchall()]
    connection_pool.putconn(conn)
    return days


def get_saved_data(user_id, selected_date):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('SELECT systolic, diastolic, pulse, time FROM user_input WHERE user_id = %s AND date = %s',
                   (user_id, selected_date))
    data = cursor.fetchall()
    connection_pool.putconn(conn)
    return data


def get_saved_month_data(user_id, selected_date):
    conn = connection_pool.getconn()
    cursor = conn.cursor()
    cursor.execute('SELECT systolic, diastolic, pulse, date FROM user_input WHERE user_id = %s AND date like %s',
                   (user_id, selected_date))
    data = cursor.fetchall()
    connection_pool.putconn(conn)
    return data


@bot.message_handler(commands=['notify'])
def notify_handler(message):
    ntf_time = get_notify_value(message.chat.id)
    if ntf_time:
        bot.send_message(message.chat.id, f"Notification is enabled at: {str(ntf_time)[:5]}")
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
    cursor.execute("SELECT notify_time, enabled FROM notifications WHERE user_id=%s", (user_id,))
    result = cursor.fetchone()
    connection_pool.putconn(conn)
    if result[1]:
        return result[0]
    else:
        return False


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


def run_notify_loop():
    while True:
        notify_loop()
        time.sleep(60)


logging.debug("Checking tables.")
create_table()
create_notification_table()
logging.debug("Tables check done.")
thread = threading.Thread(target=run_notify_loop)
thread.start()
logging.debug("Notify thread started.")

try:
    bot.polling()
    logging.debug("Bot main thread started.")
except Exception as e:
    print(e)
    bot.close()
finally:
    bot.polling()
    logging.warning(f"Restarted bot. Exception: {str(e)} ")
