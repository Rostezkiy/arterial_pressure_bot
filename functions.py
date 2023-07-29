import logging
import time
from datetime import datetime
from io import BytesIO
import psycopg2
from matplotlib import pyplot as plt
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from telebot import types
from bot import bot, config, connection_pool


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


def run_notify_loop():
    while True:
        notify_loop()
        time.sleep(60)


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
