import telebot
from telebot import types
import json
import os
import requests
from dotenv import load_dotenv
import threading
import time

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')  # Или вставь токен сюда в кавычках
PASSWORD = "130290"             # Пароль для доступа
FEE_PERCENT = 0.9               # Комиссия P2P при продаже (%)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'p2p_db.json')

bot = telebot.TeleBot(TOKEN)

# Временное хранилище для сессий
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
            'monitor_buy': False,
            'monitor_sell': False,
            'last_buy_price': None,
            'last_sell_price': None
        }
        save_db(db)
    return db[uid]

def update_user_db_field(user_id, key, val):
    db = load_db()
    uid = str(user_id)
    if uid not in db: get_user_db(user_id)
    db[uid][key] = val
    save_db(db)

# --- СКАНЕР СТАКАНА ---
def fetch_p2p_ads(type_side="buy", desired_amount=1000, limit=10):
    """
    type_side: 'buy' - смотрим объявления продажи USDT (мы покупаем)
               'sell' - смотрим объявления покупки USDT (мы продаем)
    desired_amount: сумма сделки для фильтра API (100 = объявления, поддерживающие ~100 грн)
    """
    req_type = "sale" if type_side == "buy" else "purchase"
    
    url = "https://p2p.wallet.tg/gw/p2p/items"
    
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
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            return {"ok": True, "data": response.json().get('data', [])}
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def build_stack_text(ads, side_ru, amount_info=""):
    if not ads:
        return "Стакан пуст."
    
    text = f"📋 <b>ТОП-{len(ads)} {side_ru}</b> {amount_info}:\n\n"
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
    markup.add("🔍 Стакан BUY", "🔍 Стакан SELL")
    markup.add("🔔 Мониторинг BUY", "🔔 Мониторинг SELL")
    bot.send_message(chat_id, "🤖 <b>P2P Терминал активен</b>", reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    ud = get_user_db(uid)
    if not ud.get('auth'):
        msg = bot.send_message(message.chat.id, "🔒 Введите пароль доступа:")
        bot.register_next_step_handler(msg, check_pass)
    else:
        main_menu(message.chat.id)

def check_pass(message):
    if message.text.strip() == PASSWORD:
        update_user_db_field(message.from_user.id, 'auth', True)
        bot.send_message(message.chat.id, "✅ Доступ разрешен.")
        main_menu(message.chat.id)
    else:
        msg = bot.send_message(message.chat.id, "❌ Неверно. Попробуйте еще раз:")
        bot.register_next_step_handler(msg, check_pass)

# ==========================================
# 1. РАСЧЕТ КРУГА (улучшен)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def step_1_uah(message):
    uid = message.chat.id
    USER_STATE[uid] = {}
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("5700", "5800", "10000", "29000")
    
    msg = bot.send_message(uid, "1️⃣ <b>Сумма входа (ГРН):</b>\nНа сколько закупаем USDT?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, step_2_buy_rate)

def step_2_buy_rate(message):
    val = to_float(message.text)
    if val is None:
        bot.send_message(message.chat.id, "⚠ Нужно число.")
        return main_menu(message.chat.id)
    
    USER_STATE[message.chat.id]['start_uah'] = val
    
    scan = fetch_p2p_ads("buy", desired_amount=1000, limit=5)
    best_price = "43.50"
    if scan['ok'] and scan['data']:
        best_price = scan['data'][0]['price']

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(str(best_price))

    msg = bot.send_message(message.chat.id, f"2️⃣ <b>Курс ПОКУПКИ USDT:</b>\nПочем берем? (подсказка: {best_price})", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, step_3_sell_rate)

def step_3_sell_rate(message):
    val = to_float(message.text)
    if val is None: return main_menu(message.chat.id)
    
    USER_STATE[message.chat.id]['buy_rate'] = val
    
    start_uah = USER_STATE[message.chat.id]['start_uah']
    usdt_amount = start_uah / val
    USER_STATE[message.chat.id]['usdt_amount'] = usdt_amount
    
    break_even = val / (1 - (FEE_PERCENT/100))

    scan = fetch_p2p_ads("sell", desired_amount=1000, limit=5)
    best_sell = "45.50"
    if scan['ok'] and scan['data']:
        best_sell = scan['data'][0]['price']

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(str(best_sell))

    text = (f"🛒 Куплено: <b>{usdt_amount:.4f} USDT</b>\n"
            f"⛔ Точка безубыточности: <b>{break_even:.4f}</b>\n\n"
            f"3️⃣ <b>Курс ПРОДАЖИ USDT:</b>\nПочем продаем? (подсказка: {best_sell})")
            
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, step_4_result)

def step_4_result(message):
    sell_rate = to_float(message.text)
    if sell_rate is None: return main_menu(message.chat.id)
    
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
    
    res = (f"🏁 <b>РЕЗУЛЬТАТ КРУГА:</b>\n\n"
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
# 2. СКАНЕР СТАКАНА (ручной)
# ==========================================
@bot.message_handler(func=lambda m: m.text.startswith("🔍 Стакан"))
def scan_handler(message):
    side = "buy" if "BUY" in message.text else "sell"
    side_ru = "ПОКУПКИ USDT (мы покупаем)" if side == "buy" else "ПРОДАЖИ USDT (мы продаем)"
    
    msg = bot.send_message(message.chat.id, "📡 Сканирую Wallet...")
    
    res = fetch_p2p_ads(side, desired_amount=1000, limit=10)
    
    if not res['ok']:
        bot.edit_message_text(f"Ошибка API: {res['error']}", message.chat.id, msg.message_id)
        return

    text = build_stack_text(res['data'], side_ru, "(для ~1000 грн)")
    
    bot.edit_message_text(text, message.chat.id, msg.message_id, parse_mode="HTML")

# ==========================================
# 3. МОНИТОРИНГ (новое)
# ==========================================
def send_monitor_update(uid, side):
    side_ru = "ПОКУПКИ USDT" if side == "buy" else "ПРОДАЖИ USDT"
    desired = 100
    res = fetch_p2p_ads(side, desired_amount=desired, limit=10)
    
    if not res['ok'] or not res['data']:
        bot.send_message(uid, f"❌ Нет данных для мониторинга {side_ru}")
        return
    
    best_price = float(res['data'][0]['price'])
    text = build_stack_text(res['data'], side_ru, f"(для ~{desired} грн)")
    bot.send_message(uid, text, parse_mode="HTML")
    
    update_user_db_field(uid, f'last_{side}_price', best_price)

@bot.message_handler(func=lambda m: m.text.startswith("🔔 Мониторинг"))
def monitor_toggle(message):
    side = "buy" if "BUY" in message.text else "sell"
    side_ru = "покупки" if side == "buy" else "продажи"
    
    user_db = get_user_db(message.from_user.id)
    current = user_db.get(f'monitor_{side}', False)
    new_state = not current
    
    update_user_db_field(message.from_user.id, f'monitor_{side}', new_state)
    
    status = "включён ✅" if new_state else "выключен ❌"
    bot.send_message(message.chat.id, f"🔔 Мониторинг {side_ru} {status}\nФильтр: объявления от 100 грн.")
    
    if new_state and user_db.get(f'last_{side}_price') is None:
        send_monitor_update(message.from_user.id, side)

def monitor_loop():
    while True:
        time.sleep(30)  # Проверка каждые 30 секунд
        db = load_db()
        for uid_str in list(db.keys()):
            uid = int(uid_str)
            user = db[uid_str]
            
            for side in ['buy', 'sell']:
                if user.get(f'monitor_{side}', False):
                    last_price = user.get(f'last_{side}_price')
                    res = fetch_p2p_ads(side, desired_amount=100, limit=10)
                    
                    if res['ok'] and res['data']:
                        current_best = float(res['data'][0]['price'])
                        
                        if last_price is None:
                            send_monitor_update(uid, side)
                            continue
                        
                        # Для BUY лучше когда цена ниже, для SELL — выше
                        if (side == 'buy' and current_best < last_price) or \
                           (side == 'sell' and current_best > last_price):
                            send_monitor_update(uid, side)
                            bot.send_message(uid, f"🟢 УЛУЧШЕНИЕ! Новый лучший курс {side_ru(side)}: {current_best}")
                        elif abs(current_best - last_price) >= 0.01:
                            send_monitor_update(uid, side)
                            bot.send_message(uid, f"🔄 Курс {side_ru(side)} изменился: {last_price} → {current_best}")

def side_ru(side):
    return "покупки USDT" if side == "buy" else "продажи USDT"

# ==========================================
# 4. МОЙ КАПИТАЛ (без изменений, работает хорошо)
# ==========================================
@bot.message_handler(func=lambda m: m.text == "📊 Мой капитал")
def cap_1(message):
    db = get_user_db(message.from_user.id)
    saved_inv = db.get('start_inv', 0)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(str(saved_inv))
    
    msg = bot.send_message(message.chat.id, "1️⃣ Какой был <b>стартовый депозит</b> (всего вложено)?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, cap_2)

# ... (остальная часть функции cap_2, cap_3, cap_4 осталась без изменений, как в твоём коде)

# --- ЗАПУСК ---
if __name__ == '__main__':
    print("Бот запущен...")
    # Запускаем фоновый мониторинг
    threading.Thread(target=monitor_loop, daemon=True).start()
    
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except (Exception, KeyboardInterrupt) as e:
        print(f"Ошибка: {e}")