import telebot
from telebot import types
import json
import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')
PASSWORD = "130290"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'p2p_db.json')

bot = telebot.TeleBot(TOKEN)

# --- УТИЛИТЫ ---
def to_float(text):
    if not text: return None
    try:
        return float(text.replace(',', '.').strip())
    except ValueError:
        return None

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
        # start_inv - это общий депозит за всё время (4420)
        db[uid] = {'auth': False, 'cycle_uah': 0.0, 'cycle_usdt': 0.0, 'buy_rate': 0.0, 'sell_rate': 0.0, 'start_inv': 4420.0}
        save_db(db)
    return db[uid]

def update_ud(user_id, key, val):
    db = load_db()
    db[str(user_id)][key] = float(val)
    save_db(db)

# --- СКАНЕР СТАКАНА (POST - рабочий) ---
def fetch_real_ads(user_intent="BUY"):
    url = "https://p2p.wallet.tg/gw/p2p/items"
    
    # "sale" - объявления продавцов (мы покупаем у них)
    # "purchase" - объявления покупателей (мы продаем им)
    req_type = "sale" if user_intent == "BUY" else "purchase"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://p2p.wallet.tg",
        "Referer": "https://p2p.wallet.tg/",
        "x-requested-with": "XMLHttpRequest"
    }
    
    payload = {
        "asset": "USDT",
        "fiat": "UAH",
        "type": req_type,
        "filter": { "amount": 100 },
        "limit": 5,
        "offset": 0
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            return {"ok": True, "data": response.json().get('data', [])}
        else:
            return {"ok": False, "error": f"Code {response.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- МЕНЮ ---
def main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💸 Расчет круга", "📊 Общий профит")
    markup.add("🔍 Сканер стакана")
    bot.send_message(message.chat.id, "<b>Меню:</b>", reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['start'])
def start(message):
    ud = get_ud(message.from_user.id)
    if not ud.get('auth'):
        msg = bot.send_message(message.chat.id, "🔒 Пароль:")
        bot.register_next_step_handler(msg, check_pass)
    else:
        main_menu(message)

def check_pass(message):
    if message.text.strip() == PASSWORD:
        update_ud(message.from_user.id, 'auth', 1)
        bot.send_message(message.chat.id, "✅ Ок.")
        main_menu(message)
    else:
        bot.register_next_step_handler(bot.send_message(message.chat.id, "❌ Пароль:"), check_pass)

# ==========================================
# 1. РАСЧЕТ КРУГА (КАК ТЫ ПРОСИЛ)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def circ_1(message):
    ud = get_ud(message.from_user.id)
    # Спрашиваем СТАРТОВЫЙ БАЛАНС ГРН для этого круга
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('cycle_uah'): markup.add(f"{ud['cycle_uah']}")
    
    msg = bot.send_message(message.chat.id, "1️⃣ Сколько <b>ГРН</b> на карте (сумма входа)?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_2)

def circ_2(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
    update_ud(message.from_user.id, 'cycle_uah', val)
    
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("0")
    if ud.get('cycle_usdt'): markup.add(f"{ud['cycle_usdt']}")
    
    msg = bot.send_message(message.chat.id, "2️⃣ Сколько уже есть <b>USDT</b> на кошельке?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_3)

def circ_3(message):
    val = to_float(message.text)
    if val is None: val = 0.0
    update_ud(message.from_user.id, 'cycle_usdt', val)
    
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('buy_rate'): markup.add(f"{ud['buy_rate']}")
    
    msg = bot.send_message(message.chat.id, "3️⃣ Курс <b>BUY</b> (закуп):", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_4)

def circ_4(message):
    rate = to_float(message.text)
    if rate is None: return main_menu(message)
    update_ud(message.from_user.id, 'buy_rate', rate)
    
    ud = get_ud(message.from_user.id)
    
    # Считаем промежуточно: сколько купим
    bought = ud['cycle_uah'] / rate
    total_usdt = bought + ud['cycle_usdt']
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('sell_rate'): markup.add(f"{ud['sell_rate']}")
    
    text = (f"🔸 Купим: {bought:.2f} USDT\n"
            f"🔸 Было: {ud['cycle_usdt']} USDT\n"
            f"👉 <b>Всего сливаем: {total_usdt:.2f} USDT</b>\n\n"
            f"4️⃣ Введи курс <b>SELL</b> (продажа):")
    
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_final)

def circ_final(message):
    sell_rate = to_float(message.text)
    if sell_rate is None: return main_menu(message)
    update_ud(message.from_user.id, 'sell_rate', sell_rate)
    
    ud = get_ud(message.from_user.id)
    
    # Логика:
    # 1. Купили на (cycle_uah) по (buy_rate)
    bought_usdt = ud['cycle_uah'] / ud['buy_rate']
    # 2. Плюсуем то что было
    total_usdt = bought_usdt + ud['cycle_usdt']
    # 3. Сливаем всё
    dirty_uah = total_usdt * sell_rate
    clean_uah = dirty_uah * 0.991 # минус комса 0.9%
    
    # 4. Профит = Чистый Выход - Вход ГРН
    profit = clean_uah - ud['cycle_uah']
    
    res = (f"🏁 <b>ИТОГ КРУГА:</b>\n"
           f"📉 Вход: {ud['cycle_uah']} грн\n"
           f"📈 Выход (чистыми): {clean_uah:.2f} грн\n"
           f"➖➖➖➖➖➖\n"
           f"🤑 <b>ПРИБЫЛЬ: {profit:+.2f} грн</b>")
    
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message)

# ==========================================
# 2. ОБЩИЙ ПРОФИТ (Твой запрос)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "📊 Общий профит")
def total_1(message):
    msg = bot.send_message(message.chat.id, "1️⃣ Баланс <b>ГРН на карте</b> сейчас:", parse_mode="HTML")
    bot.register_next_step_handler(msg, total_2)

def total_2(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
    
    bot.user_data = getattr(bot, 'user_data', {})
    if message.chat.id not in bot.user_data: bot.user_data[message.chat.id] = {}
    bot.user_data[message.chat.id]['t_card'] = val
    
    msg = bot.send_message(message.chat.id, "2️⃣ Баланс <b>USDT</b> сейчас:", parse_mode="HTML")
    bot.register_next_step_handler(msg, total_3)

def total_3(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
    bot.user_data[message.chat.id]['t_usdt'] = val
    
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('sell_rate'): markup.add(f"{ud['sell_rate']}")
    
    msg = bot.send_message(message.chat.id, "3️⃣ Курс продажи USDT (оценка):", reply_markup=markup)
    bot.register_next_step_handler(msg, total_4)

def total_4(message):
    rate = to_float(message.text)
    if rate is None: return main_menu(message)
    bot.user_data[message.chat.id]['t_rate'] = rate
    
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(f"{ud.get('start_inv', 4420)}") # По дефолту твои 4420
    
    msg = bot.send_message(message.chat.id, "4️⃣ Сколько всего было <b>ВЛОЖЕНО СВОИХ</b> (депозит)?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, total_final)

def total_final(message):
    inv = to_float(message.text)
    if inv is None: return main_menu(message)
    update_ud(message.from_user.id, 'start_inv', inv)
    
    d = bot.user_data[message.chat.id]
    
    # Активы в грн
    usdt_in_uah = (d['t_usdt'] * d['t_rate']) * 0.991
    total_assets = d['t_card'] + usdt_in_uah
    
    # Чистый профит = Активы - Депозит
    profit = total_assets - inv
    
    res = (f"📊 <b>ВСЯ КАССА:</b>\n"
           f"💳 Карта: {d['t_card']} грн\n"
           f"💵 Крипта: ~{usdt_in_uah:.2f} грн\n"
           f"💰 <b>Всего денег: {total_assets:.2f} грн</b>\n"
           f"🔻 Вложено: {inv} грн\n"
           f"➖➖➖➖➖➖\n"
           f"🚀 <b>ЧИСТЫЙ ПРОФИТ: {profit:+.2f} грн</b>")
    
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message)

# ==========================================
# 3. СКАНЕР (ОТЛАЖЕННЫЙ)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "🔍 Сканер стакана")
def scan(message):
    bot.send_message(message.chat.id, "📡 Запрос в Wallet...")
    
    buy = fetch_real_ads("BUY")
    sell = fetch_real_ads("SELL")
    
    txt = ""
    
    # BUY (Мы покупаем -> ищем продавцов)
    if buy['ok']:
        txt += "📥 <b>ЗАКУП (Нам продают):</b>\n"
        for i in buy['data'][:3]: # топ 3
            price = i.get('price')
            u = i.get('user', {})
            name = u.get('nickname') or u.get('name') or "Anon"
            l_min = i.get('min_amount')
            l_max = i.get('max_amount')
            txt += f"🔹 <b>{price}</b> | {name} | {l_min}-{l_max}\n"
        if not buy['data']: txt += "Пусто.\n"
    else:
        txt += f"⚠ Ошибка BUY: {buy['error']}\n"
    
    txt += "\n"
    
    # SELL (Мы продаем -> ищем покупателей)
    if sell['ok']:
        txt += "📤 <b>ПРОДАЖА (У нас покупают):</b>\n"
        for i in sell['data'][:3]:
            price = i.get('price')
            u = i.get('user', {})
            name = u.get('nickname') or u.get('name') or "Anon"
            l_min = i.get('min_amount')
            l_max = i.get('max_amount')
            txt += f"🔸 <b>{price}</b> | {name} | {l_min}-{l_max}\n"
        if not sell['data']: txt += "Пусто.\n"
    else:
        txt += f"⚠ Ошибка SELL: {sell['error']}\n"
        
    bot.send_message(message.chat.id, txt, parse_mode="HTML")

if __name__ == '__main__':
    bot.infinity_polling()
