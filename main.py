import telebot
from telebot import types
import json
import os
import time
import threading
import requests
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
# Вставь сюда токен своего бота
TOKEN = os.getenv('BOT_TOKEN') or "ТВОЙ_ТОКЕН_БОТА" 
PASSWORD = "130290"
FEE_PERCENT = 0.9  # Комиссия 0.9%

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'p2p_db.json')

bot = telebot.TeleBot(TOKEN)
USER_STATE = {}
MONITORING_ACTIVE = {} # {chat_id: True/False}

# --- КЛАСС API (С поддержкой обновления токена) ---
class WalletP2P:
    def __init__(self, token=None):
        self.base_url = "https://p2p.wallet.tg/gw/p2p/items"
        self.token = token
        self.update_headers()

    def update_headers(self):
        """Обновляет заголовки для запросов"""
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

    def get_ads(self, side="buy", amount=1000):
        if not self.token or len(self.token) < 20:
            return "NO_TOKEN"
            
        req_type = "sale" if side == "buy" else "purchase"
        payload = {
            "asset": "USDT",
            "fiat": "UAH",
            "type": req_type,
            "filter": {"amount": amount},
            "limit": 10,
            "offset": 0
        }
        try:
            resp = requests.post(self.base_url, headers=self.headers, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('data', [])
            elif resp.status_code == 401:
                return "TOKEN_EXPIRED"
            else:
                return []
        except Exception as e:
            print(f"API Error: {e}")
            return []

    def get_best_price(self, side="buy"):
        ads = self.get_ads(side)
        if ads in ["TOKEN_EXPIRED", "NO_TOKEN"]:
            return ads
        if not ads:
            return 0.0
        return float(ads[0]['price'])

# Инициализация API (без токена, подхватится из БД)
api = WalletP2P()

# --- БАЗА ДАННЫХ ---
def load_db():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

def get_user_db(uid):
    db = load_db()
    uid = str(uid)
    if uid not in db:
        db[uid] = {'auth': False}
        save_db(db)
    return db[uid]

def update_db(uid, key, val):
    db = load_db()
    if str(uid) not in db: get_user_db(uid)
    db[str(uid)][key] = val
    save_db(db)

# Загружаем сохраненный токен при запуске
db_init = load_db()
if db_init.get('global_wallet_token'):
    api.set_token(db_init['global_wallet_token'])

# --- УТИЛИТЫ ---
def to_float(text):
    if not text: return None
    try: return float(text.replace(',', '.').strip())
    except: return None

# --- ФОНОВЫЙ МОНИТОРИНГ ---
def monitoring_loop():
    while True:
        active_users = [uid for uid, active in MONITORING_ACTIVE.items() if active]
        if active_users:
            buy_price = api.get_best_price("buy")
            sell_price = api.get_best_price("sell")
            
            if isinstance(buy_price, float) and isinstance(sell_price, float) and buy_price > 0:
                my_buy = buy_price + 0.01
                my_sell = sell_price - 0.01
                res = (my_sell * (1 - FEE_PERCENT/100)) - my_buy
                spread_pct = (res / my_buy) * 100
                
                if spread_pct > 1.5:
                    msg = (f"🔔 <b>СИГНАЛ P2P!</b>\n"
                           f"Спред: <b>{spread_pct:.2f}%</b>\n"
                           f"Buy (Maker): {my_buy:.2f} | Sell (Maker): {my_sell:.2f}")
                    for uid in active_users:
                        try: bot.send_message(uid, msg, parse_mode="HTML")
                        except: MONITORING_ACTIVE[uid] = False
        time.sleep(60)

threading.Thread(target=monitoring_loop, daemon=True).start()

# --- ЛОГИКА БОТА ---
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    ud = get_user_db(uid)
    if not ud.get('auth'):
        msg = bot.send_message(uid, "🔒 Введи пароль доступа:")
        bot.register_next_step_handler(msg, check_pass)
    else:
        main_menu(uid)

def check_pass(message):
    if message.text.strip() == PASSWORD:
        update_db(message.chat.id, 'auth', True)
        bot.send_message(message.chat.id, "✅ Доступ открыт")
        main_menu(message.chat.id)
    else:
        bot.register_next_step_handler(bot.send_message(message.chat.id, "❌ Неверно. Еще раз:"), check_pass)

def main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("💸 Расчет круга", "🔍 Сканер P2P")
    markup.add("📡 Мониторинг ВКЛ", "🔕 Мониторинг ВЫКЛ")
    markup.add("⚙ Обновить токен")
    bot.send_message(chat_id, "Главное меню:", reply_markup=markup)

# --- РАБОТА С ТОКЕНОМ ---
@bot.message_handler(func=lambda m: m.text == "⚙ Обновить токен")
def ask_token_file(message):
    bot.send_message(message.chat.id, "📄 Пришли мне **.txt файл**, в котором внутри только токен (Bearer eyJ...).")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    if message.document.file_name.endswith('.txt'):
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        token_text = downloaded_file.decode('utf-8').strip()
        
        if len(token_text) > 50:
            api.set_token(token_text)
            db = load_db()
            db['global_wallet_token'] = token_text
            save_db(db)
            bot.send_message(message.chat.id, "✅ Токен успешно загружен из файла и сохранен!")
            main_menu(message.chat.id)
        else:
            bot.send_message(message.chat.id, "❌ Файл пуст или содержит неверный токен.")
    else:
        bot.send_message(message.chat.id, "❌ Пришли именно текстовый (.txt) файл.")

# --- ФУНКЦИИ P2P ---
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def calc_start(message):
    bot.send_message(message.chat.id, "⏳ Опрашиваю маркет...")
    b_rate = api.get_best_price("buy")
    s_rate = api.get_best_price("sell")
    
    if b_rate == "TOKEN_EXPIRED":
        bot.send_message(message.chat.id, "⚠ Токен протух! Обнови его через файл.")
        return
    if b_rate == "NO_TOKEN":
        bot.send_message(message.chat.id, "⚠ Токен еще не загружен.")
        return

    USER_STATE[message.chat.id] = {'buy_rate': b_rate, 'sell_rate': s_rate}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("5700", "10000", "25000")
    msg = bot.send_message(message.chat.id, f"📊 Курсы: Buy {b_rate} / Sell {s_rate}\nВведите сумму входа (ГРН):", reply_markup=markup)
    bot.register_next_step_handler(msg, calc_final)

def calc_final(message):
    uah_in = to_float(message.text)
    if not uah_in: return main_menu(message.chat.id)
    
    data = USER_STATE.get(message.chat.id, {})
    buy = data.get('buy_rate', 0)
    sell = data.get('sell_rate', 0)
    
    usdt = uah_in / buy
    total = (usdt * sell) * (1 - FEE_PERCENT/100)
    profit = total - uah_in
    
    res = (f"🧾 <b>ИТОГ:</b>\nКурс: {buy} -> {sell}\n"
           f"💰 Вход: {uah_in} грн\n"
           f"💎 Выход: {total:.2f} грн\n"
           f"📈 Профит: <b>{profit:+.2f} грн</b>")
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message.chat.id)

@bot.message_handler(func=lambda m: m.text == "🔍 Сканер P2P")
def scanner(message):
    bot.send_message(message.chat.id, "🔎 Получаю топ стаканов...")
    buy_ads = api.get_ads("buy")
    sell_ads = api.get_ads("sell")
    
    txt = "📊 <b>TOP-3 Wallet:</b>\n\n"
    txt += "📉 <b>Купить (Taker):</b>\n"
    if isinstance(buy_ads, list):
        for ad in buy_ads[:3]: txt += f"▫ {ad['price']} | {ad['user'].get('nickname')}\n"
    
    txt += "\n📈 <b>Продать (Taker):</b>\n"
    if isinstance(sell_ads, list):
        for ad in sell_ads[:3]: txt += f"▫ {ad['price']} | {ad['user'].get('nickname')}\n"
        
    bot.send_message(message.chat.id, txt, parse_mode="HTML")

@bot.message_handler(func=lambda m: "Мониторинг" in m.text)
def toggle_monitor(message):
    state = "ВКЛ" in message.text
    MONITORING_ACTIVE[message.chat.id] = state
    bot.send_message(message.chat.id, f"{'✅ Запущен' if state else '🔕 Выключен'}")

if __name__ == '__main__':
    bot.infinity_polling()
