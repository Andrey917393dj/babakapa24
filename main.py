import telebot
import os
import requests
import json
import time
from telebot import types
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')
PASSWORD = "130290"
# Путь к базе данных в папке со скриптом
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'p2p_db.json')

bot = telebot.TeleBot(TOKEN)

# --- БАЗА ДАННЫХ ---
def load_db():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f: 
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_ud(user_id):
    db = load_db()
    uid = str(user_id)
    if uid not in db:
        db[uid] = {'auth': False, 'bal': 0.0, 'buy': 0.0, 'sell': 0.0, 'start_inv': 0.0, 'usdt_wallet': 0.0}
        save_db(db)
    return db[uid]

def update_ud(user_id, key, val):
    db = load_db()
    db[str(user_id)][key] = val
    save_db(db)

# --- РЕАЛЬНЫЙ ЧЕКЕР WALLET ---
def fetch_wallet_ads(ad_type="BUY"):
    """
    ad_type: "BUY" (мы покупаем у них) или "SELL" (мы продаем им)
    """
    url = "https://walletbot.me/api/v1/p2p/advertisements"
    params = {
        "fiat": "UAH",
        "crypto": "USDT",
        "type": ad_type,
        "payment": ["Monobank"], # Можно добавить другие через запятую
        "amount": 100,
        "page": 1
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {"success": True, "items": data.get('data', [])[:2]} # Берем первые 2
        else:
            return {"success": False, "error": f"Ошибка сервера: {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- МЕНЮ ---
def main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💸 Расчет круга", "📊 Общий профит")
    markup.add("🔍 Живой Мониторинг", "🛡 Безопасность")
    bot.send_message(message.chat.id, "<b>Выбери действие:</b>", reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['start'])
def start(message):
    ud = get_ud(message.from_user.id)
    if not ud.get('auth'):
        sent = bot.send_message(message.chat.id, "🔒 Введите пароль доступа:")
        bot.register_next_step_handler(sent, check_pass)
    else:
        main_menu(message)

def check_pass(message):
    if message.text == PASSWORD:
        update_ud(message.from_user.id, 'auth', True)
        bot.send_message(message.chat.id, "✅ Доступ открыт!")
        main_menu(message)
    else:
        sent = bot.send_message(message.chat.id, "❌ Неверно. Пароль:")
        bot.register_next_step_handler(sent, check_pass)

# --- МОНИТОРИНГ ---
@bot.message_handler(func=lambda m: m.text == "🔍 Живой Мониторинг")
def monitor(message):
    bot.send_message(message.chat.id, "📡 Запрос к Wallet P2P...")
    
    buy_data = fetch_wallet_ads("BUY")
    sell_data = fetch_wallet_ads("SELL")
    
    if not buy_data['success'] or not sell_data['success']:
        error_msg = buy_data.get('error') or sell_data.get('error')
        bot.send_message(message.chat.id, f"❌ <b>Ошибка мониторинга:</b>\n<code>{error_msg}</code>", parse_mode="HTML")
        return

    res = "📥 <b>ЗАКУП (Вы покупаете):</b>\n"
    for item in buy_data['items']:
        res += f"• <b>{item['price']}</b> | {item['user']['name']} | Лимит: {item['min_amount']}-{item['max_amount']}\n"
    
    res += "\n📤 <b>ПРОДАЖА (Вы продаете):</b>\n"
    for item in sell_data['items']:
        res += f"• <b>{item['price']}</b> | {item['user']['name']} | Лимит: {item['min_amount']}-{item['max_amount']}\n"

    bot.send_message(message.chat.id, res, parse_mode="HTML")

# --- КАЛЬКУЛЯТОР КРУГА (ПОЭТАПНО) ---
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def circle_1(message):
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud['bal'] > 0: markup.add(f"Оставить {ud['bal']}")
    sent = bot.send_message(message.chat.id, "Баланс закупа (грн):", reply_markup=markup)
    bot.register_next_step_handler(sent, circle_2)

def circle_2(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'bal', float(val))
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud['buy'] > 0: markup.add(f"Оставить {ud['buy']}")
    sent = bot.send_message(message.chat.id, "Курс BUY:", reply_markup=markup)
    bot.register_next_step_handler(sent, circle_3)

def circle_3(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'buy', float(val))
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud['sell'] > 0: markup.add(f"Оставить {ud['sell']}")
    sent = bot.send_message(message.chat.id, "Курс SELL:", reply_markup=markup)
    bot.register_next_step_handler(sent, circle_fin)

def circle_fin(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'sell', float(val))
    ud = get_ud(message.from_user.id)
    
    usdt = ud['bal'] / ud['buy']
    clean_out = (usdt * ud['sell']) * 0.991
    profit = clean_out - ud['bal']
    
    res = (f"📈 <b>Круг завершен:</b>\n"
           f"💰 Вход: <code>{ud['bal']} грн</code>\n"
           f"📤 Чистыми: <b>{clean_out:.2f} грн</b>\n"
           f"🤑 Профит: <b>+{profit:.2f} грн</b>")
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message)

# --- ОБЩИЙ ПРОФИТ ---
@bot.message_handler(func=lambda m: m.text == "📊 Общий профит")
def total_1(message):
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if ud['usdt_wallet'] > 0: markup.add(f"Оставить {ud['usdt_wallet']}")
    sent = bot.send_message(message.chat.id, "USDT на кошельке:", reply_markup=markup)
    bot.register_next_step_handler(sent, total_2)

def total_2(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'usdt_wallet', float(val))
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if ud['start_inv'] > 0: markup.add(f"Оставить {ud['start_inv']}")
    sent = bot.send_message(message.chat.id, "Стартовые вложения (грн):", reply_markup=markup)
    bot.register_next_step_handler(sent, total_fin)

def total_fin(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'start_inv', float(val))
    ud = get_ud(message.from_user.id)
    
    current = (ud['usdt_wallet'] * ud['sell']) + ud['bal']
    profit = current - ud['start_inv']
    
    bot.send_message(message.chat.id, f"🚀 Твой чистый профит за всё время: <b>{profit:.2f} грн</b>", parse_mode="HTML")
    main_menu(message)

@bot.message_handler(func=lambda m: m.text == "🛡 Безопасность")
def safety(message):
    bot.send_message(message.chat.id, "1. Деньги на карту.\n2. Сверяй ФИО.\n3. Не верь чекам.")

if __name__ == '__main__':
    bot.infinity_polling()
