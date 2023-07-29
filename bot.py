import configparser
import psycopg2
import telebot
from psycopg2 import pool

config = configparser.ConfigParser()
config.read('config.ini')
bot = telebot.TeleBot(config.get('TG', 'token'))

connection_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=config.get('DB', 'minconn'),
    maxconn=config.get('DB', 'maxconn'),
    host=config.get('DB', 'host'),
    port=config.get('DB', 'port'),
    database=config.get('DB', 'database'),
    user=config.get('DB', 'user'),
    password=config.get('DB', 'password')
)