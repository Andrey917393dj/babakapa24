import telebot
import os
import subprocess
import signal
import time
import sys
from telebot import types

# --- НАСТРОЙКИ ---
HOST_TOKEN = "ТОКЕН_ХОСТ_БОТА" 
PASSWORD = "130290"

# Пути (делаем абсолютными, чтобы не зависеть от места запуска)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.join(BASE_DIR, "app_data")
TARGET_SCRIPT = os.path.join(RUN_DIR, "main.py")
REQ_FILE = os.path.join(RUN_DIR, "requirements.txt")
LOG_FILE = os.path.join(RUN_DIR, "bot_log.txt")

if not os.path.exists(RUN_DIR):
    os.makedirs(RUN_DIR)

bot = telebot.TeleBot(HOST_TOKEN)
current_process = None
user_auth = {}

def stop_old_bot():
    global current_process
    # 1. Пробуем остановить через переменную
    if current_process:
        try:
            os.kill(current_process.pid, signal.SIGTERM)
        except:
            pass
    # 2. Жесткая зачистка всех процессов main.py в папке app_data
    try:
        subprocess.run(["pkill", "-f", "app_data/main.py"], check=False)
    except:
        pass
    time.sleep(1)

def start_new_bot(target_bot_token):
    global current_process
    stop_old_bot()
    
    # Передаем токен через env
    env = os.environ.copy()
    env["BOT_TOKEN"] = target_bot_token
    # Добавляем путь к библиотекам, если они локальные
    env["PYTHONPATH"] = BASE_DIR

    with open(LOG_FILE, "w") as l_file:
        l_file.write(f"--- Запуск бота: {time.ctime()} ---\n")
        
    # Запускаем процесс
    current_process = subprocess.Popen(
        [sys.executable, TARGET_SCRIPT],
        env=env,
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        cwd=RUN_DIR # Запускаем строго внутри папки с файлом
    )
    return current_process.pid

@bot.message_handler(commands=['start'])
def start(message):
    user_auth[message.chat.id] = False
    bot.send_message(message.chat.id, "🔐 Введите пароль хоста:")

@bot.message_handler(func=lambda m: not user_auth.get(m.chat.id, False))
def auth(message):
    if message.text == PASSWORD:
        user_auth[message.chat.id] = True
        show_main_menu(message)
    else:
        bot.send_message(message.chat.id, "❌ Отказ.")

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🚀 Деплой (Загрузить код)", "🛑 Стоп")
    markup.add("📋 Логи", "⚡️ Статус")
    bot.send_message(message.chat.id, "🕹 Управление сервером:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "⚡️ Статус")
def status_check(message):
    global current_process
    if current_process and current_process.poll() is None:
        bot.send_message(message.chat.id, f"✅ Бот работает.\nPID: {current_process.pid}")
    else:
        bot.send_message(message.chat.id, "🔴 Бот остановлен или упал.")

@bot.message_handler(func=lambda m: m.text == "🚀 Деплой (Загрузить код)")
def deploy_start(message):
    sent = bot.send_message(message.chat.id, "1️⃣ Введите BOT_TOKEN рабочего бота:")
    bot.register_next_step_handler(sent, step_get_token)

def step_get_token(message):
    token = message.text.strip()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Пропустить (уже есть)")
    sent = bot.send_message(message.chat.id, "2️⃣ Скиньте файл `requirements.txt`:", reply_markup=markup)
    bot.register_next_step_handler(sent, step_get_req, token)

def step_get_req(message, token):
    if message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        with open(REQ_FILE, 'wb') as f:
            f.write(bot.download_file(file_info.file_path))
        bot.send_message(message.chat.id, "⏳ Установка библиотек...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", REQ_FILE])
    
    sent = bot.send_message(message.chat.id, "3️⃣ Скиньте файл `main.py`:")
    bot.register_next_step_handler(sent, step_get_script, token)

def step_get_script(message, token):
    if message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        with open(TARGET_SCRIPT, 'wb') as f:
            f.write(bot.download_file(file_info.file_path))
        
        try:
            pid = start_new_bot(token)
            bot.send_message(message.chat.id, f"🚀 Бот запущен!\nPID: {pid}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка старта: {e}")
    else:
        bot.send_message(message.chat.id, "Нужен файл!")

@bot.message_handler(func=lambda m: m.text == "🛑 Стоп")
def stop_all(message):
    stop_old_bot()
    bot.send_message(message.chat.id, "🔴 Все процессы остановлены.")

@bot.message_handler(func=lambda m: m.text == "📋 Логи")
def send_logs(message):
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "rb") as f:
            bot.send_document(message.chat.id, f)
    else:
        bot.send_message(message.chat.id, "Лог-файл не найден.")

bot.infinity_polling()
