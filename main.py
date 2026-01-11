import telebot
from telebot import types
import json
import os
import requests
from dotenv import load_dotenv
import threading
import time
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# Отключаем предупреждения о небезопасном соединении (SSL проблема у TG Wallet)
requests.disable_warnings(InsecureRequestWarning)

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
PASSWORD = "130290"

FEE_PERCENT = 0.9  # Комиссия Telegram Wallet P2P при продаже

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'p2p_db.json')

bot = telebot.TeleBot(TOKEN)

USER_STATE = {}

# --- УТИЛИТЫ ---
def to_float(text):
    if not text: return None
    try:
        return float(text.replace(',', '.').strip())
    except ValueError:
        return None

def load_db():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_db(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user_db(user_id):
    db = load_db()
    uid = str(user_id)
    if uid not in db:
        db[uid] = {
            'auth': False,
            'start_inv': 5700.0,
            'auto_buy': False,
            'auto_sell': False,
            'monitor_limit': 10,
            'monitor_interval': 30,
            'monitor_min_amount': 100,  # Фильтр по минимальной сумме сделки
            'last_buy_price': None,
            'last_sell_price': None,
            'last_check_buy': 0.0,
            'last_check_sell': 0.0
        }
        save_db(db)
    return db[uid]

def update_user_db(user_id, updates):
    db = load_db()
    uid = str(user_id)
    if uid not in db: get_user_db(user_id)
    db[uid].update(updates)
    save_db(db)

# --- TELEGRAM WALLET P2P API (с verify=False из-за проблемы сертификата) ---
URL = "https://p2p.wallet.tg/gw/p2p/items"

def fetch_p2p_ads(side="buy", desired_amount=100, limit=10):
    """
    side: 'buy' — стакан продавцов (мы покупаем USDT)
          'sell' — стакан покупателей (мы продаём USDT)
    desired_amount: сумма сделки для фильтра (объявления, подходящие под эту сумму)
    """
    req_type = "sale" if side == "buy" else "purchase"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://p2p.wallet.tg",
        "x-requested-with": "XMLHttpRequest"
    }
    
    payload = {
        "asset": "USDT",
        "fiat": "UAH",
        "type": req_type,
        "filter": {"amount": desired_amount},
        "limit": limit,
        "offset": 0
    }
    
    try:
        response = requests.post(URL, headers=headers, json=payload, timeout=10, verify=False)
        if response.status_code == 200:
            return {"ok": True, "data": response.json().get('data', [])}
        return {"ok": False, "error": f"HTTP {response.status_code}: {response.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def build_stack_text(ads, side_ru, extra=""):
    if not ads:
        return "Стакан пуст или нет подходящих объявлений."
    
    text = f"📋 <b>ТОП-{len(ads)} {side_ru} Telegram Wallet P2P</b> {extra}:\n\n"
    for i, ad in enumerate(ads, 1):
        price = ad.get('price')
        user = ad.get('user', {})
        name = user.get('nickname') or "Аноним"
        min_a = int(float(ad.get('min_amount', 0)))
        max_a = int(float(ad.get('max_amount', 0)))
        
        text += f"{i}. <b>{price}</b> | {name}\n   Лимит: {min_a} - {max_a} грн\n\n"
    
    return text

# --- МЕНЮ ---
def main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("💸 Расчет круга", "📊 Мой капитал")
    markup.add("⚙️ Проверка и настройки P2P")
    bot.send_message(chat_id, "🤖 <b>P2P Терминал активен (Telegram Wallet)</b>", reply_markup=markup, parse_mode="HTML")

def p2p_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🔍 Проверить BUY", "🔍 Проверить SELL")
    markup.add("⚙️ Настройки автомониторинга")
    markup.add("🔙 В главное меню")
    bot.send_message(chat_id, "⚙️ <b>Проверка и настройки P2P (TG Wallet)</b>", reply_markup=markup, parse_mode="HTML")

def settings_menu(chat_id, user_db):
    auto_buy = "вкл ✅" if user_db['auto_buy'] else "выкл ❌"
    auto_sell = "вкл ✅" if user_db['auto_sell'] else "выкл ❌"
    
    text = (f"🔔 <b>Настройки автомониторинга</b>\n\n"
            f"Авто BUY: {auto_buy}\n"
            f"Авто SELL: {auto_sell}\n"
            f"Кол-во объявлений: {user_db['monitor_limit']}\n"
            f"Частота проверки: {user_db['monitor_interval']} сек\n"
            f"Фильтр суммы сделки: от ~{user_db['monitor_min_amount']} грн\n")
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🔄 Toggle авто BUY", "🔄 Toggle авто SELL")
    markup.add("📊 Изменить кол-во", "⏱ Изменить частоту", "💰 Изменить фильтр суммы")
    markup.add("🔙 Назад")
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

# --- ХЕНДЛЕРЫ ---
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    ud = get_user_db(uid)
    if not ud.get('auth'):
        msg = bot.send_message(message.chat.id, "🔒 Введите пароль:")
        bot.register_next_step_handler(msg, check_pass)
    else:
        main_menu(message.chat.id)

def check_pass(message):
    if message.text.strip() == PASSWORD:
        update_user_db(message.from_user.id, {'auth': True})
        bot.send_message(message.chat.id, "✅ Доступ разрешен.")
        main_menu(message.chat.id)
    else:
        msg = bot.send_message(message.chat.id, "❌ Неверно. Еще раз:")
        bot.register_next_step_handler(msg, check_pass)

@bot.message_handler(func=lambda m: m.text == "⚙️ Проверка и настройки P2P")
def p2p_handler(message):
    p2p_menu(message.chat.id)

@bot.message_handler(func=lambda m: m.text == "🔙 В главное меню")
def back_to_main(message):
    main_menu(message.chat.id)

@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_p2p(message):
    p2p_menu(message.chat.id)

@bot.message_handler(func=lambda m: m.text.startswith("🔍 Проверить"))
def manual_scan(message):
    side = "buy" if "BUY" in message.text else "sell"
    side_ru = "ПОКУПКИ USDT (мы покупаем)" if side == "buy" else "ПРОДАЖИ USDT (мы продаём)"
    
    user_db = get_user_db(message.from_user.id)
    desired = user_db['monitor_min_amount']
    lim = user_db['monitor_limit']
    
    msg = bot.send_message(message.chat.id, "📡 Сканирую Telegram Wallet...")
    
    res = fetch_p2p_ads(side, desired_amount=desired, limit=lim)
    
    if not res['ok']:
        bot.edit_message_text(f"Ошибка: {res['error']}", message.chat.id, msg.message_id)
        return
    
    text = build_stack_text(res['data'], side_ru, f"(для ~{desired} грн)")
    bot.edit_message_text(text, message.chat.id, msg.message_id, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки автомониторинга")
def show_settings(message):
    user_db = get_user_db(message.from_user.id)
    settings_menu(message.chat.id, user_db)

@bot.message_handler(func=lambda m: m.text.startswith("🔄 Toggle авто"))
def toggle_auto(message):
    uid = message.from_user.id
    user_db = get_user_db(uid)
    if "BUY" in message.text:
        new_val = not user_db['auto_buy']
        update_user_db(uid, {'auto_buy': new_val})
        status = "включён ✅" if new_val else "выключен ❌"
        bot.send_message(message.chat.id, f"Авто BUY {status}")
    else:
        new_val = not user_db['auto_sell']
        update_user_db(uid, {'auto_sell': new_val})
        status = "включён ✅" if new_val else "выключен ❌"
        bot.send_message(message.chat.id, f"Авто SELL {status}")
    settings_menu(message.chat.id, get_user_db(uid))

def change_param(message, param_name, prompt, min_v, max_v, is_int=True):
    val_text = message.text.strip()
    val = to_float(val_text)
    if val is None or val < min_v or val > max_v or (is_int and not val.is_integer()):
        msg = bot.send_message(message.chat.id, f"⚠ Неверно. {prompt}")
        bot.register_next_step_handler(msg, lambda m: change_param(m, param_name, prompt, min_v, max_v, is_int))
        return
    
    if is_int:
        val = int(val)
    update_user_db(message.from_user.id, {param_name: val})
    bot.send_message(message.chat.id, f"✅ Установлено: {val}")
    settings_menu(message.chat.id, get_user_db(message.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📊 Изменить кол-во")
def ch_limit(message):
    msg = bot.send_message(message.chat.id, "Кол-во объявлений (5-20):")
    bot.register_next_step_handler(msg, lambda m: change_param(m, 'monitor_limit', "Введите 5-20", 5, 20, True))

@bot.message_handler(func=lambda m: m.text == "⏱ Изменить частоту")
def ch_interval(message):
    msg = bot.send_message(message.chat.id, "Частота проверки в секундах (15-300):")
    bot.register_next_step_handler(msg, lambda m: change_param(m, 'monitor_interval', "Введите 15-300", 15, 300, True))

@bot.message_handler(func=lambda m: m.text == "💰 Изменить фильтр суммы")
def ch_min_amount(message):
    msg = bot.send_message(message.chat.id, "Минимальная сумма сделки для фильтра (100-5000 грн):")
    bot.register_next_step_handler(msg, lambda m: change_param(m, 'monitor_min_amount', "Введите 100-5000", 100, 5000, True))

# ==========================================
# РАСЧЕТ КРУГА (с комиссией 0.9% и подсказками из TG Wallet)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def step_1_uah(message):
    uid = message.chat.id
    USER_STATE[uid] = {}
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("5700", "5800", "10000", "29000")
    
    msg = bot.send_message(uid, "1️⃣ <b>Сумма входа (ГРН):</b>", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, step_2_buy_rate)

def step_2_buy_rate(message):
    val = to_float(message.text)
    if val is None or val <= 0:
        msg = bot.send_message(message.chat.id, "⚠ Введите число >0")
        bot.register_next_step_handler(msg, step_2_buy_rate)
        return
    
    USER_STATE[message.chat.id]['start_uah'] = val
    
    scan = fetch_p2p_ads("buy", desired_amount=1000, limit=3)
    best_price = "43.00"
    if scan['ok'] and scan['data']:
        best_price = scan['data'][0]['price']

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(best_price)
    
    msg = bot.send_message(message.chat.id, f"2️⃣ <b>Курс ПОКУПКИ USDT:</b>\n(подсказка: {best_price})", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, step_3_sell_rate)

def step_3_sell_rate(message):
    val = to_float(message.text)
    if val is None or val <= 0:
        msg = bot.send_message(message.chat.id, "⚠ Введите число >0")
        bot.register_next_step_handler(msg, step_3_sell_rate)
        return
    
    USER_STATE[message.chat.id]['buy_rate'] = val
    
    start_uah = USER_STATE[message.chat.id]['start_uah']
    usdt_amount = start_uah / val
    USER_STATE[message.chat.id]['usdt_amount'] = usdt_amount
    
    break_even = val / (1 - FEE_PERCENT/100)

    scan = fetch_p2p_ads("sell", desired_amount=1000, limit=3)
    best_sell = "45.00"
    if scan['ok'] and scan['data']:
        best_sell = scan['data'][0]['price']

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(best_sell)
    
    text = (f"🛒 Куплено: <b>{usdt_amount:.4f} USDT</b>\n"
            f"⛔ Точка безубыточности: <b>{break_even:.4f}</b> (с учётом комиссии {FEE_PERCENT}%)\n\n"
            f"3️⃣ <b>Курс ПРОДАЖИ USDT:</b>\n(подсказка: {best_sell})")
            
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, step_4_result)

def step_4_result(message):
    sell_rate = to_float(message.text)
    if sell_rate is None or sell_rate <= 0:
        msg = bot.send_message(message.chat.id, "⚠ Введите число >0")
        bot.register_next_step_handler(msg, step_4_result)
        return
    
    data = USER_STATE[message.chat.id]
    buy_rate = data['buy_rate']
    start_uah = data['start_uah']
    usdt_amount = data['usdt_amount']
    
    dirty_uah = usdt_amount * sell_rate
    fee_val = dirty_uah * (FEE_PERCENT / 100)
    clean_uah = dirty_uah - fee_val
    profit = clean_uah - start_uah
    
    spread = ((sell_rate - buy_rate) / buy_rate) * 100
    roi = (profit / start_uah) * 100 if start_uah > 0 else 0
    
    icon = "🟢" if profit > 0 else "🔴"
    
    res = (f"🏁 <b>РЕЗУЛЬТАТ КРУГА (TG Wallet):</b>\n\n"
           f"💵 Вход: <code>{start_uah:.2f} грн</code>\n"
           f"🔄 Курсы: {buy_rate} → {sell_rate}\n"
           f"📊 Грязный спред: {spread:.2f}%\n"
           f"💸 Комиссия {FEE_PERCENT}%: -{fee_val:.2f} грн\n"
           f"➖➖➖➖➖➖➖➖\n"
           f"💰 Выход чистыми: <b>{clean_uah:.2f} грн</b>\n"
           f"{icon} <b>PROFIT: {profit:+.2f} грн</b>\n"
           f"📈 <b>ROI: {roi:.2f}%</b>")
    
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message.chat.id)

# ==========================================
# МОЙ КАПИТАЛ
# ==========================================
@bot.message_handler(func=lambda m: m.text == "📊 Мой капитал")
def cap_1(message):
    db = get_user_db(message.from_user.id)
    saved_inv = db.get('start_inv', 5700.0)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(str(saved_inv))
    
    msg = bot.send_message(message.chat.id, "1️⃣ <b>Стартовый депозит (всего вложено):</b>", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, cap_2)

def cap_2(message):
    inv = to_float(message.text)
    if inv is None or inv < 0:
        msg = bot.send_message(message.chat.id, "⚠ Введите число ≥0")
        bot.register_next_step_handler(msg, cap_2)
        return
    update_user_db(message.from_user.id, {'start_inv': inv})
    USER_STATE[message.chat.id] = {'total_inv': inv}
    
    msg = bot.send_message(message.chat.id, "2️⃣ <b>Сколько сейчас ГРН на картах?</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, cap_3)

def cap_3(message):
    val = to_float(message.text)
    if val is None or val < 0:
        msg = bot.send_message(message.chat.id, "⚠ Введите число ≥0")
        bot.register_next_step_handler(msg, cap_3)
        return
    USER_STATE[message.chat.id]['fiat_now'] = val
    
    msg = bot.send_message(message.chat.id, "3️⃣ <b>Сколько сейчас USDT на кошельке?</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, cap_4)

def cap_4(message):
    usdt = to_float(message.text)
    if usdt is None or usdt < 0:
        msg = bot.send_message(message.chat.id, "⚠ Введите число ≥0")
        bot.register_next_step_handler(msg, cap_4)
        return
    USER_STATE[message.chat.id]['usdt_now'] = usdt
    
    scan = fetch_p2p_ads("sell", desired_amount=1000, limit=1)
    est_rate = 45.0
    if scan['ok'] and scan['data']:
        est_rate = float(scan['data'][0]['price'])

    data = USER_STATE[message.chat.id]
    crypto_in_fiat = (usdt * est_rate) * (1 - FEE_PERCENT/100)
    
    total_assets = data['fiat_now'] + crypto_in_fiat
    total_profit = total_assets - data['total_inv']
    
    res = (f"💼 <b>АУДИТ КАПИТАЛА:</b>\n"
           f"💳 Фиат: {data['fiat_now']:.2f} грн\n"
           f"🪙 Крипта: {usdt:.4f} USDT (~{crypto_in_fiat:.0f} грн с учётом комиссии)\n"
           f"➖➖➖➖➖➖\n"
           f"💰 <b>Всего: {total_assets:.2f} грн</b>\n"
           f"📉 Вложено: {data['total_inv']:.2f} грн\n"
           f"🚀 <b>ПЛЮС: {total_profit:+.2f} грн</b>")
           
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message.chat.id)

# ==========================================
# АВТОМОНИТОРИНГ
# ==========================================
def monitor_loop():
    while True:
        time.sleep(15)
        current_time = time.time()
        db = load_db()
        for uid_str, user in db.items():
            uid = int(uid_str)
            for side, auto_key, check_key, price_key in [
                ("buy", "auto_buy", "last_check_buy", "last_buy_price"),
                ("sell", "auto_sell", "last_check_sell", "last_sell_price")
            ]:
                if user.get(auto_key, False):
                    interval = user['monitor_interval']
                    if current_time - user.get(check_key, 0) >= interval:
                        desired = user['monitor_min_amount']
                        lim = user['monitor_limit']
                        res = fetch_p2p_ads(side, desired_amount=desired, limit=lim)
                        update_user_db(uid, {check_key: current_time})
                        
                        if res['ok'] and res['data']:
                            current_best = float(res['data'][0]['price'])
                            last_price = user.get(price_key)
                            
                            side_ru = "ПОКУПКИ USDT" if side == "buy" else "ПРОДАЖИ USDT"
                            text = build_stack_text(res['data'], side_ru, f"(для ~{desired} грн)")
                            
                            send_update = False
                            note = ""
                            if last_price is None:
                                send_update = True
                            elif side == "buy" and current_best < last_price - 0.01:
                                send_update = True
                                note = f"🟢 УЛУЧШЕНИЕ! Цена ниже: {current_best}"
                            elif side == "sell" and current_best > last_price + 0.01:
                                send_update = True
                                note = f"🟢 УЛУЧШЕНИЕ! Цена выше: {current_best}"
                            elif abs(current_best - last_price) >= 0.05:
                                send_update = True
                                note = f"🔄 Курс изменился: {last_price} → {current_best}"
                            
                            if send_update:
                                if note:
                                    bot.send_message(uid, note)
                                bot.send_message(uid, text, parse_mode="HTML")
                                update_user_db(uid, {price_key: current_best})

# --- ЗАПУСК ---
if __name__ == '__main__':
    print("Бот запущен (Telegram Wallet P2P)...")
    threading.Thread(target=monitor_loop, daemon=True).start()
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Ошибка: {e}")