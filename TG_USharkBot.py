import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import time
import random
import requests
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TGTOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not TOKEN:
    raise ValueError("BOT_TOKEN не задан! Проверь .env")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID не задан! Проверь .env")

ADMIN_ID = int(ADMIN_ID)

bot = telebot.TeleBot(TOKEN)

# ---------- SQLITE ----------

db = sqlite3.connect("bot.db", check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
cursor = db.cursor()

# база сообщений
cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT UNIQUE
)
""")

# база блэклиста
cursor.execute("""
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT UNIQUE
)
""")

db.commit()

forwarded_messages = {}
reply_in_progress = {}

#---------------ФУНКЦИИ------------------

def log_to_admin(message, extra_text=""):
    """
    Пересылает сообщение админу и логирует текст и медиа.
    """
    try:
        # Пересылаем любое сообщение
        forwarded = bot.forward_message(
            ADMIN_ID,
            message.chat.id,
            message.message_id
        )
        # Сохраняем связь пересланного → оригинальный пользователь
        forwarded_messages[forwarded.message_id] = message.from_user.id

        # Инлайн-кнопка "Ответить"
        keyboard = types.InlineKeyboardMarkup()
        button = types.InlineKeyboardButton(
            text="Ответить",
            callback_data=f"reply_{forwarded.message_id}"
        )
        keyboard.add(button)

        bot.send_message(
            ADMIN_ID,
            f"📩 Новое сообщение от {message.from_user.first_name} {extra_text}",
            reply_markup=keyboard
        )

        # Логируем в консоль
        print(f"[ЛОГ] {message.from_user.first_name} ({message.from_user.id}) -> {message.chat.id}: {getattr(message, 'text', '[не текст]')}")
    except Exception as e:
        print("Ошибка пересылки админу:", e)

#---------------ХЕНДЛЕРЫ-----------------

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Приветик! Я миленький фембойчик! 🤖")

# 🔹 Логирование всех сообщений
@bot.message_handler(content_types=[
    'text', 'photo', 'video', 'document', 'audio',
    'voice', 'sticker', 'animation'
])
def log_all_messages(message):
    try:
        
        if message.from_user.is_bot:
            return
            
        if message.chat.id == ADMIN_ID and message.text and message.text.startswith("🤖"):
            return
            
        if message.text:
            text_lower = message.text.lower()
        
            cursor.execute("SELECT word FROM blacklist")
            words = cursor.fetchall()

            for word in words:
                if word[0] in text_lower:
                    return

# ---------- ЕСЛИ ЭТО АДМИН ----------
        if message.from_user.id == ADMIN_ID:

    # если админ отвечает пользователю через кнопку
            if message.from_user.id in reply_in_progress:
                handle_admin_response(message)
                return

            # если просто написал сообщение — бот отвечает рандомно
            cursor.execute("SELECT COUNT(*) FROM messages")
            count = cursor.fetchone()[0]

            if count > 0 and message.text:

                cursor.execute(
                    "SELECT text FROM messages ORDER BY RANDOM() LIMIT 1"
                )
            
                result = cursor.fetchone()
            
                if result:
                    reply = result[0]
            
                    if reply != message.text:
                        bot.send_message(message.chat.id, reply)
            
                        bot.send_message(
                            ADMIN_ID,
                            f"🤖 Бот ответил ТЕБЕ:\n{reply}"
                        )

            return

# -------- ЕСЛИ ЭТО ПОЛЬЗОВАТЕЛЬ ---------

        if message.text:
            text = message.text.strip()

            if len(text) > 2 and not text.startswith("/"):
                cursor.execute(
                    "INSERT OR IGNORE INTO messages(text) VALUES(?)",
                    (text,)
                )
                db.commit()

            cursor.execute(
                "SELECT text FROM messages ORDER BY RANDOM() LIMIT 1"
            )

            result = cursor.fetchone()

            if result:
                reply = result[0]

                if reply != message.text:
                    bot.send_message(message.chat.id, reply)

                    bot.send_message(
                        ADMIN_ID,
                        f"🤖 Бот ответил пользователю {message.from_user.first_name} ({message.from_user.id}):\n{reply}"
                    )

        # пересылаем админу
        log_to_admin(message)

    except Exception as e:
        print("Ошибка логирования:", e)

# 🔹 Обработка кнопки "Ответить"
@bot.callback_query_handler(func=lambda call: call.data.startswith("reply_"))
def handle_reply_button(call):
    original_id = int(call.data.split("_")[1])
    reply_in_progress[call.from_user.id] = original_id
    bot.send_message(call.from_user.id, "✏️ Напиши ответ на сообщение")
    bot.answer_callback_query(call.id)

# 🔹 Ответ администратора
@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID)
def handle_admin_response(message):
    if message.from_user.id in reply_in_progress:
        original_message_id = reply_in_progress.pop(message.from_user.id)
        if original_message_id in forwarded_messages:
            user_id = forwarded_messages[original_message_id]
            try:
                bot.send_message(user_id, message.text)
                log_to_admin(message, extra_text="(ответ администратора)")
            except Exception as e:
                print("Ошибка отправки:", e)
                
@bot.message_handler(commands=['bl'])
def add_blacklist(message):

    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.send_message(message.chat.id, "Напиши команду: /bl слово")
        return

    word = parts[1].lower()

    cursor.execute(
        "SELECT word FROM blacklist WHERE word=?",
        (word,)
    )

    exists = cursor.fetchone()

    if exists:
        bot.send_message(message.chat.id, "Это слово уже в блэк-листе")
        return

    cursor.execute(
        "INSERT INTO blacklist(word) VALUES(?)",
        (word,)
    )

    db.commit()

    bot.send_message(
        message.chat.id,
        f"🚫 Добавлено в блэк-лист: {word}"
    )

# 🔹 Основной цикл
print("Бот запущен...")
last_status = 0

while True:
    try:
        bot.polling(
            none_stop=True, 
            timeout=60,
            long_polling_timeout=60
        )
    except (requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
            ApiTelegramException) as e:
        print("Соединение разорвано, пытаюсь переподключиться...")
        time.sleep(5)
    except Exception as e:
        # Это любые другие ошибки в коде
        print("Произошла ошибка в боте:", e)
        # НЕ переподключаемся автоматически
        break

    now = time.time()
    if now - last_status > 30:
        print("Бот работает...")
        last_status = now