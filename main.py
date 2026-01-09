import telebot
import os
import subprocess
import signal
import time
from telebot import types

# Конфиг хоста
HOST_TOKEN = "ТОКЕН_ЭТОГО_БОТА_ХОСТА" # Токен бота, который будет управлять хостингом
PASSWORD = "130290"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.join(BASE_DIR, "running_bot")
TARGET_SCRIPT = os.path.join(RUN_DIR, "main.py")
REQ_FILE = os.path.join(RUN_DIR, "requirements.txt")

bot = telebot.TeleBot(HOST_TOKEN)

# Хранилище текущего процесса запущенного бота
current_process = None
user_auth = {}

if not os.path.exists(RUN_DIR):
    os.makedirs(RUN_DIR)

def stop_old_bot():
    global current_process
    if current_process:
        try:
            os.kill(current_process.pid, signal.SIGTERM)
            print("Старый бот остановлен.")
        except:
            pass
    # На случай если процесс завис, убиваем по имени файла через систему
    subprocess.run(["pkill", "-f", "running_bot/main.py"])

def start_new_bot(target_bot_token):
    global current_process
    stop_old_bot()
    
    # Запускаем с передачей токена через переменную окружения
    env = os.environ.copy()
    env["BOT_TOKEN"] = target_bot_token
    
    log_file = open(os.path.join(RUN_DIR, "bot_log.txt"), "a")
    current_process = subprocess.Popen(
        ["python3", TARGET_SCRIPT],
        env=env,
        stdout=log_file,
        stderr=log_file
    )
    return current_process.pid

@bot.message_handler(commands=['start'])
def start(message):
    user_auth[message.chat.id] = False
    bot.send_message(message.chat.id, "🔐 Введите пароль управления хостом:")

@bot.message_handler(func=lambda m: not user_auth.get(m.chat.id, False))
def auth(message):
    if message.text == PASSWORD:
        user_auth[message.chat.id] = True
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🚀 Запустить нового бота", "🛑 Остановить", "📋 Логи")
        bot.send_message(message.chat.id, "✅ Доступ разрешен. Управляйте сервером:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ Неверно.")

@bot.message_handler(func=lambda m: m.text == "🚀 Запустить нового бота")
def ask_token(message):
    sent = bot.send_message(message.chat.id, "1️⃣ Введите BOT_TOKEN для рабочего бота:")
    bot.register_next_step_handler(sent, save_token_step)

def save_token_step(message):
    token = message.text
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Пропустить")
    sent = bot.send_message(message.chat.id, "2️⃣ Пришлите файл `requirements.txt` (документом) или нажмите Пропустить:", reply_markup=markup)
    bot.register_next_step_handler(sent, save_req_step, token)

def save_req_step(message, token):
    if message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(REQ_FILE, 'wb') as f:
            f.write(downloaded_file)
        bot.send_message(message.chat.id, "📦 Устанавливаю зависимости...")
        subprocess.run(["pip", "install", "-r", REQ_FILE])
    
    sent = bot.send_message(message.chat.id, "3️⃣ Пришлите файл `main.py` (документом):")
    bot.register_next_step_handler(sent, save_script_step, token)

def save_script_step(message, token):
    if message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(TARGET_SCRIPT, 'wb') as f:
            f.write(downloaded_file)
        
        pid = start_new_bot(token)
        bot.send_message(message.chat.id, f"🚀 Бот запущен! PID: {pid}")
    else:
        bot.send_message(message.chat.id, "❌ Ошибка: нужен файл .py")

@bot.message_handler(func=lambda m: m.text == "🛑 Остановить")
def stop_handler(message):
    stop_old_bot()
    bot.send_message(message.chat.id, "🛑 Бот выключен.")

@bot.message_handler(func=lambda m: m.text == "📋 Логи")
def send_logs(message):
    log_path = os.path.join(RUN_DIR, "bot_log.txt")
    if os.path.exists(log_path):
        with open(log_path, "rb") as f:
            bot.send_document(message.chat.id, f)
    else:
        bot.send_message(message.chat.id, "Логи пока пусты.")

bot.infinity_polling()
