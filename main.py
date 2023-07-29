import threading

import bot
from functions import connect_to_db, create_table, create_notification_table, run_notify_loop
import handlers  # register the handlers, do not remove!


def main():
    connect_to_db()
    create_table()
    create_notification_table()
    thread = threading.Thread(target=run_notify_loop)
    thread.start()
    bot.bot.polling()
    print("Ready.")


if __name__ == '__main__':
    main()
