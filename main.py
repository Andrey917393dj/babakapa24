import telebot
from telebot import types
import json
import os
import requests
import urllib3 # Добавили для отключения варнингов
from dotenv import load_dotenv

# Отключаем предупреждения об отсутствии проверки SSL в консоли
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN') 
PASSWORD = "130290"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'p2p_db.json')

bot = telebot.TeleBot(TOKEN)

class WalletP2P:
    def __init__(self, token=None):
        self.base_url = "https://p2p.wallet.tg/gw/p2p/items"
        self.balance_url = "https://p2p.wallet.tg/gw/wallet/v1/balances"
        self.token = token
        self.update_headers()

    def update_headers(self):
        auth_value = self.token if (self.token and self.token.startswith("Bearer")) else f"Bearer {self.token}"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://p2p.wallet.tg",
            "Authorization": auth_value,
            "x-requested-with": "XMLHttpRequest",
            "Content-Type": "application/json"
        }

    def set_token(self, new_token):
        self.token = new_token.strip()
        self.update_headers()

    def test_connection(self):
        try:
            # Добавили verify=False, чтобы обойти ошибку сертификата
            resp = requests.get(self.balance_url, headers=self.headers, timeout=10, verify=False)
            if resp.status_code == 200:
                return True, resp.json()
            return False, f"Код: {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def get_ads(self, side="buy", amount=1000):
        if not self.token: return "NO_TOKEN"
        req_type = "sale" if side == "buy" else "purchase"
        payload = {"asset": "USDT", "fiat": "UAH", "type": req_type, "filter": {"amount": amount}, "limit": 10, "offset": 0}
        try:
            # Добавили verify=False
            resp = requests.post(self.base_url, headers=self.headers, json=payload, timeout=10, verify=False)
            if resp.status_code == 200: return resp.json().get('data', [])
            if resp.status_code == 401: return "TOKEN_EXPIRED"
            return []
        except: return []

# --- ОСТАЛЬНАЯ ЛОГИКА БОТА ---
def load_db():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

api = WalletP2P()
db_init = load_db()
if db_init.get('global_wallet_token'):
    api.set_token(db_init['global_wallet_token'])

@bot.message_handler(commands=['start'])
def start(message):
    msg = bot.send_message(message.chat.id, "🔒 Пароль:")
    bot.register_next_step_handler(msg, lambda m: main_menu(m.chat.id) if m.text == PASSWORD else bot.send_message(m.chat.id, "Нет"))

def main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💸 Расчет круга", "🔍 Сканер P2P", "⚙ Обновить токен")
    bot.send_message(chat_id, "Меню:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "⚙ Обновить токен")
def ask_file(message):
    bot.send_message(message.chat.id, "Пришли .txt с токеном")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    if message.document.file_name.endswith('.txt'):
        status_msg = bot.send_message(message.chat.id, "⏳ Проверяю коннект (SSL Bypass)...")
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        token_text = downloaded_file.decode('utf-8').strip()
        
        api.set_token(token_text)
        is_ok, result = api.test_connection()
        
        if is_ok:
            db = load_db()
            db['global_wallet_token'] = token_text
            save_db(db)
            bot.edit_message_text("✅ КОННЕКТ УСПЕШЕН!", message.chat.id, status_msg.message_id)
            main_menu(message.chat.id)
        else:
            bot.edit_message_text(f"❌ ОШИБКА: {result}", message.chat.id, status_msg.message_id)

@bot.message_handler(func=lambda m: m.text == "🔍 Сканер P2P")
def scan(message):
    res = api.get_ads("buy")
    if res == "TOKEN_EXPIRED": bot.send_message(message.chat.id, "Токен протух")
    elif isinstance(res, list): bot.send_message(message.chat.id, f"Связь есть! Найдено {len(res)} заявок.")

if __name__ == '__main__':
    print("Бот запущен с обходом SSL...")
    bot.infinity_polling()
