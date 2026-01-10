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
    """Превращает текст с запятой или точкой в число"""
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
        # start_inv по умолчанию ставим 4420 (твои вложения), но можно менять
        db[uid] = {'auth': False, 'bal_uah': 0.0, 'buy_rate': 0.0, 'sell_rate': 0.0, 'extra_usdt': 0.0, 'start_inv': 4420.0}
        save_db(db)
    return db[uid]

def update_ud(user_id, key, val):
    db = load_db()
    db[str(user_id)][key] = float(val)
    save_db(db)

# --- МОНИТОРИНГ (Запрос к API) ---
def fetch_real_ads(ad_type="BUY"):
    # Эндпоинт, который используется веб-версией
    url = "https://walletbot.me/api/v1/p2p/advertisements" 
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    params = {
        "fiat": "UAH",
        "crypto": "USDT",
        "type": ad_type, # BUY или SELL
        "amount": 100,   # Фильтр от 100 грн
        "page": 1
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            return {"ok": True, "data": response.json().get('data', [])}
        else:
            return {"ok": False, "error": f"HTTP {response.status_code}"}
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
        msg = bot.send_message(message.chat.id, "🔒 Введи пароль:")
        bot.register_next_step_handler(msg, check_pass)
    else:
        main_menu(message)

def check_pass(message):
    if message.text.strip() == PASSWORD:
        update_ud(message.from_user.id, 'auth', 1)
        bot.send_message(message.chat.id, "✅ Доступ есть.")
        main_menu(message)
    else:
        bot.register_next_step_handler(bot.send_message(message.chat.id, "❌ Пароль:"), check_pass)

# =======================
# 1. РАСЧЕТ КРУГА (ИСПРАВЛЕННЫЙ)
# =======================
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def circ_1(message):
    ud = get_ud(message.from_user.id)
    # Предлагаем прошлое значение
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('bal_uah'): markup.add(f"{ud['bal_uah']}")
    
    msg = bot.send_message(message.chat.id, "1️⃣ Введи сумму <b>UAH</b> для закупа:", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_2)

def circ_2(message):
    val = to_float(message.text)
    if val is None: 
        bot.send_message(message.chat.id, "⚠️ Нужно число. Жми заново.", reply_markup=types.ReplyKeyboardRemove())
        return main_menu(message)
    
    update_ud(message.from_user.id, 'bal_uah', val)
    
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('buy_rate'): markup.add(f"{ud['buy_rate']}")
    
    msg = bot.send_message(message.chat.id, "2️⃣ Почем берем? Курс <b>BUY</b>:", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_3)

def circ_3(message):
    buy_rate = to_float(message.text)
    if buy_rate is None: return main_menu(message)
    
    uid = message.from_user.id
    update_ud(uid, 'buy_rate', buy_rate)
    ud = get_ud(uid)
    
    # Считаем, сколько купим
    bought_usdt = ud['bal_uah'] / buy_rate
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("0") # Кнопка для быстрого ввода
    if ud.get('extra_usdt'): markup.add(f"{ud['extra_usdt']}")
    
    text = (f"✅ На {ud['bal_uah']} грн ты купишь <code>{bought_usdt:.4f} USDT</code>\n\n"
            f"3️⃣ Сколько <b>USDT уже есть</b> на балансе? (Введи 0, если пусто):")
    
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_4)

def circ_4(message):
    extra = to_float(message.text)
    if extra is None: extra = 0.0
    
    uid = message.from_user.id
    update_ud(uid, 'extra_usdt', extra)
    
    ud = get_ud(uid)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('sell_rate'): markup.add(f"{ud['sell_rate']}")
    
    msg = bot.send_message(message.chat.id, "4️⃣ Почем сливаем? Курс <b>SELL</b>:", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_final)

def circ_final(message):
    sell_rate = to_float(message.text)
    if sell_rate is None: return main_menu(message)
    
    uid = message.from_user.id
    update_ud(uid, 'sell_rate', sell_rate)
    ud = get_ud(uid)
    
    # Расчет
    bought_usdt = ud['bal_uah'] / ud['buy_rate']
    total_usdt = bought_usdt + ud['extra_usdt']
    
    dirty_uah = total_usdt * sell_rate
    # Комиссия 0.9% (умножаем на 0.991)
    clean_uah = dirty_uah * 0.991
    
    # Профит = То что получили - То что потратили сейчас
    # Внимание: тут считаем профит круга. Если добавленные USDT были "бесплатные", это профит.
    # Но обычно считают: (Выход - Вход UAH). 
    # Если extra_usdt > 0, расчет сложнее, но покажем просто итоговую сумму.
    
    res = (f"🏁 <b>Результат:</b>\n"
           f"🔸 Куплено: {bought_usdt:.2f} USDT\n"
           f"🔸 Было доп: {ud['extra_usdt']:.2f} USDT\n"
           f"💰 Всего на продажу: <b>{total_usdt:.2f} USDT</b>\n"
           f"➖➖➖➖➖➖\n"
           f"💵 Грязными: {dirty_uah:.2f} грн\n"
           f"💳 <b>Чистыми на карту: {clean_uah:.2f} грн</b>\n"
           f"(с учетом комсы 0.9%)")
    
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message)


# =======================
# 2. ОБЩИЙ ПРОФИТ (ИСПРАВЛЕННЫЙ)
# =======================
@bot.message_handler(func=lambda m: m.text == "📊 Общий профит")
def profit_1(message):
    msg = bot.send_message(message.chat.id, "1️⃣ Сколько <b>ГРН</b> сейчас на карте?", parse_mode="HTML")
    bot.register_next_step_handler(msg, profit_2)

def profit_2(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
    # Сохраним временно в user_data в памяти (не в базу, чтобы не путать с кругом)
    bot.user_data = getattr(bot, 'user_data', {})
    if message.chat.id not in bot.user_data: bot.user_data[message.chat.id] = {}
    bot.user_data[message.chat.id]['temp_card'] = val
    
    msg = bot.send_message(message.chat.id, "2️⃣ Сколько <b>USDT</b> на кошельке?", parse_mode="HTML")
    bot.register_next_step_handler(msg, profit_3)

def profit_3(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
    bot.user_data[message.chat.id]['temp_usdt'] = val
    
    ud = get_ud(message.from_user.id)
    # Предлагаем последний курс продажи
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('sell_rate'): markup.add(f"{ud['sell_rate']}")
    
    msg = bot.send_message(message.chat.id, "3️⃣ По какому курсу считаем USDT в грн? (Курс продажи):", reply_markup=markup)
    bot.register_next_step_handler(msg, profit_4)

def profit_4(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
    bot.user_data[message.chat.id]['temp_rate'] = val
    
    ud = get_ud(message.from_user.id)
    # Предлагаем сохраненные стартовые
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(f"{ud.get('start_inv', 4420)}")
    
    msg = bot.send_message(message.chat.id, "4️⃣ Сколько всего было <b>вложено своих</b> денег (депозит)?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, profit_final)

def profit_final(message):
    start_inv = to_float(message.text)
    if start_inv is None: return main_menu(message)
    
    # Обновляем стартовые в базе навсегда
    update_ud(message.from_user.id, 'start_inv', start_inv)
    
    data = bot.user_data[message.chat.id]
    card_money = data['temp_card']
    usdt_money = data['temp_usdt']
    rate = data['temp_rate']
    
    # Формула: (USDT * Rate * 0.991) + Card - Start
    usdt_in_uah = (usdt_money * rate) * 0.991
    total_assets = card_money + usdt_in_uah
    total_profit = total_assets - start_inv
    
    res = (f"📊 <b>Калькуляция капитала:</b>\n"
           f"💳 На карте: {card_money} грн\n"
           f"💵 В крипте: ~{usdt_in_uah:.2f} грн\n"
           f"💰 <b>Всего активов: {total_assets:.2f} грн</b>\n"
           f"🔻 Депозит: {start_inv} грн\n"
           f"➖➖➖➖➖➖\n"
           f"🚀 <b>ЧИСТЫЙ ПРОФИТ: {total_profit:.2f} грн</b>\n"
           f"Рост банка: { (total_profit/start_inv)*100 :.2f}%")
    
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message)


# =======================
# 3. СКАНЕР (РЕАЛЬНЫЙ ЗАПРОС)
# =======================
@bot.message_handler(func=lambda m: m.text == "🔍 Сканер стакана")
def scan_p2p(message):
    bot.send_message(message.chat.id, "📡 Сканирую стакан Wallet...")
    
    # 1. Получаем BUY (кого мы покупаем)
    buy_res = fetch_real_ads("BUY")
    # 2. Получаем SELL (кому мы продаем)
    sell_res = fetch_real_ads("SELL")
    
    msg = ""
    
    # Обработка BUY
    if buy_res['ok']:
        items = buy_res['data'][:2] # берем топ 2
        msg += "📥 <b>ЛУЧШИЕ ЦЕНЫ ЗАКУПА:</b>\n"
        if not items: msg += "Пусто или лимиты не подходят.\n"
        for i in items:
            price = i.get('price')
            name = i.get('user', {}).get('name', 'Anon')
            lim_min = i.get('min_amount')
            lim_max = i.get('max_amount')
            msg += f"🔹 <b>{price}</b> | {name} | {lim_min}-{lim_max}\n"
    else:
        msg += f"📥 Ошибка BUY: {buy_res['error']}\n"
        
    msg += "\n"
    
    # Обработка SELL
    if sell_res['ok']:
        items = sell_res['data'][:2]
        msg += "📤 <b>ЛУЧШИЕ ЦЕНЫ ПРОДАЖИ:</b>\n"
        if not items: msg += "Пусто.\n"
        for i in items:
            price = i.get('price')
            name = i.get('user', {}).get('name', 'Anon')
            lim_min = i.get('min_amount')
            lim_max = i.get('max_amount')
            msg += f"🔸 <b>{price}</b> | {name} | {lim_min}-{lim_max}\n"
    else:
        msg += f"📤 Ошибка SELL: {sell_res['error']}\n"
        
    bot.send_message(message.chat.id, msg, parse_mode="HTML")


if __name__ == '__main__':
    bot.infinity_polling()
