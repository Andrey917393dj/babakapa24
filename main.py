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
        db[uid] = {'auth': False, 'bal_uah': 0.0, 'buy_rate': 0.0, 'sell_rate': 0.0, 'extra_usdt': 0.0, 'start_inv': 4420.0}
        save_db(db)
    return db[uid]

def update_ud(user_id, key, val):
    db = load_db()
    db[str(user_id)][key] = float(val)
    save_db(db)

# --- НОВЫЙ СКАНЕР (FIX 404) ---
def fetch_real_ads(user_intent="BUY"):
    """
    user_intent="BUY" -> Мы хотим купить -> Ищем объявления типа 'sale' (люди продают нам)
    user_intent="SELL" -> Мы хотим продать -> Ищем объявления типа 'purchase' (люди покупают у нас)
    """
    url = "https://p2p.wallet.tg/gw/p2p/items"
    
    # Для API Wallet:
    # type "sale" = Продавцы (у них мы покупаем, кнопка BUY)
    # type "purchase" = Покупатели (им мы продаем, кнопка SELL)
    req_type = "sale" if user_intent == "BUY" else "purchase"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Content-Type": "application/json",
        "Origin": "https://p2p.wallet.tg",
        "Referer": "https://p2p.wallet.tg/",
        "x-requested-with": "XMLHttpRequest"
    }
    
    # Тело запроса (фильтры)
    payload = {
        "asset": "USDT",
        "fiat": "UAH",
        "type": req_type,
        "filter": {
            "amount": 100 # Фильтр от 100 грн
        },
        "limit": 10,
        "offset": 0
    }
    
    try:
        # Теперь используем POST
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return {"ok": True, "data": data.get('data', [])}
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
# 1. РАСЧЕТ КРУГА (FIX ПРИБЫЛИ)
# =======================
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def circ_1(message):
    ud = get_ud(message.from_user.id)
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
    
    msg = bot.send_message(message.chat.id, "2️⃣ Курс <b>BUY</b> (по чем берем?):", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_3)

def circ_3(message):
    buy_rate = to_float(message.text)
    if buy_rate is None: return main_menu(message)
    
    uid = message.from_user.id
    update_ud(uid, 'buy_rate', buy_rate)
    ud = get_ud(uid)
    
    bought_usdt = ud['bal_uah'] / buy_rate
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("0")
    if ud.get('extra_usdt'): markup.add(f"{ud['extra_usdt']}")
    
    text = (f"✅ На {ud['bal_uah']} грн выйдет <code>{bought_usdt:.4f} USDT</code>\n\n"
            f"3️⃣ Сколько <b>дополнительно USDT</b> есть на балансе? (0 если нет):")
    
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
    
    msg = bot.send_message(message.chat.id, "4️⃣ Курс <b>SELL</b> (по чем сливаем?):", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, circ_final)

def circ_final(message):
    sell_rate = to_float(message.text)
    if sell_rate is None: return main_menu(message)
    
    uid = message.from_user.id
    update_ud(uid, 'sell_rate', sell_rate)
    ud = get_ud(uid)
    
    # 1. Считаем USDT
    bought_usdt = ud['bal_uah'] / ud['buy_rate']
    total_usdt = bought_usdt + ud['extra_usdt']
    
    # 2. Считаем выход
    dirty_uah = total_usdt * sell_rate
    clean_uah = dirty_uah * 0.991 # Комиссия 0.9%
    
    # 3. Считаем ПРОФИТ (Именно для этого круга)
    # Если мы подмешивали extra_usdt, расчет профита сложнее, 
    # но обычно арбитражнику важно: (Чистый выход - (Вход UAH + Стоимость доп. USDT))
    # Для простоты считаем: Прибыль = Чистый выход - Вход UAH (Считаем что extra_usdt - это уже профит с прошлого раза)
    
    profit = clean_uah - ud['bal_uah']
    # Если были extra usdt, прибыль будет казаться огромной, это нормально, это "касса".
    
    res = (f"🏁 <b>ФИНАЛ КРУГА:</b>\n"
           f"🔸 Куплено: {bought_usdt:.2f} USDT\n"
           f"🔸 Доп. крипта: {ud['extra_usdt']:.2f} USDT\n"
           f"💰 Продаем: <b>{total_usdt:.2f} USDT</b>\n"
           f"➖➖➖➖➖➖\n"
           f"💵 Грязными: {dirty_uah:.2f} грн\n"
           f"💳 Чистыми: {clean_uah:.2f} грн\n"
           f"🤑 <b>ПРИБЫЛЬ (Навар): +{profit:.2f} грн</b>\n"
           f"(Прибыль = Чистыми - Закуп {ud['bal_uah']} грн)")
    
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message)

# =======================
# 2. ОБЩИЙ ПРОФИТ
# =======================
@bot.message_handler(func=lambda m: m.text == "📊 Общий профит")
def profit_1(message):
    msg = bot.send_message(message.chat.id, "1️⃣ Сколько <b>ГРН</b> сейчас на карте?", parse_mode="HTML")
    bot.register_next_step_handler(msg, profit_2)

def profit_2(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
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
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud.get('sell_rate'): markup.add(f"{ud['sell_rate']}")
    
    msg = bot.send_message(message.chat.id, "3️⃣ По какому курсу считать крипту? (Курс продажи):", reply_markup=markup)
    bot.register_next_step_handler(msg, profit_4)

def profit_4(message):
    val = to_float(message.text)
    if val is None: return main_menu(message)
    bot.user_data[message.chat.id]['temp_rate'] = val
    
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(f"{ud.get('start_inv', 4420)}")
    
    msg = bot.send_message(message.chat.id, "4️⃣ Сколько всего было <b>вложено своих</b> денег?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(msg, profit_final)

def profit_final(message):
    start_inv = to_float(message.text)
    if start_inv is None: return main_menu(message)
    update_ud(message.from_user.id, 'start_inv', start_inv)
    
    data = bot.user_data[message.chat.id]
    card_money = data['temp_card']
    usdt_money = data['temp_usdt']
    rate = data['temp_rate']
    
    # Считаем капитал
    usdt_in_uah = (usdt_money * rate) * 0.991
    total_assets = card_money + usdt_in_uah
    total_profit = total_assets - start_inv
    
    roi = (total_profit / start_inv) * 100 if start_inv > 0 else 0
    
    res = (f"📊 <b>ИТОГИ ДНЯ:</b>\n"
           f"💳 На карте: {card_money} грн\n"
           f"💵 В крипте: ~{usdt_in_uah:.2f} грн\n"
           f"💰 <b>Всего активов: {total_assets:.2f} грн</b>\n"
           f"🔻 Депозит: {start_inv} грн\n"
           f"➖➖➖➖➖➖\n"
           f"🚀 <b>ЧИСТЫЙ ПРОФИТ: {total_profit:.2f} грн</b>\n"
           f"📈 Рост банка: +{roi:.2f}%")
    
    bot.send_message(message.chat.id, res, parse_mode="HTML")
    main_menu(message)


# =======================
# 3. СКАНЕР (FIX 404 -> POST)
# =======================
@bot.message_handler(func=lambda m: m.text == "🔍 Сканер стакана")
def scan_p2p(message):
    bot.send_message(message.chat.id, "📡 Сканирую Wallet (POST запрос)...")
    
    buy_res = fetch_real_ads("BUY")
    sell_res = fetch_real_ads("SELL")
    
    msg = ""
    
    # Вывод BUY (Мы покупаем)
    if buy_res['ok']:
        items = buy_res['data'][:2]
        msg += "📥 <b>ТОП-2 ЗАКУП (По чем продают нам):</b>\n"
        if not items: msg += "Пусто.\n"
        for i in items:
            price = i.get('price')
            # Имя юзера может быть в разных полях в зависимости от версии API
            name = i.get('user', {}).get('nickname') or i.get('user', {}).get('name') or "Anon"
            limit = i.get('available_amount', 0) 
            # Иногда лимиты в min_amount/max_amount
            l_min = i.get('min_amount')
            l_max = i.get('max_amount')
            
            msg += f"🔹 <b>{price}</b> | {name} | {l_min}-{l_max}\n"
    else:
        msg += f"📥 Ошибка BUY: {buy_res['error']}\n"
    
    msg += "\n"
    
    # Вывод SELL (Мы продаем)
    if sell_res['ok']:
        items = sell_res['data'][:2]
        msg += "📤 <b>ТОП-2 ПРОДАЖА (По чем покупают у нас):</b>\n"
        if not items: msg += "Пусто.\n"
        for i in items:
            price = i.get('price')
            name = i.get('user', {}).get('nickname') or i.get('user', {}).get('name') or "Anon"
            l_min = i.get('min_amount')
            l_max = i.get('max_amount')
            msg += f"🔸 <b>{price}</b> | {name} | {l_min}-{l_max}\n"
    else:
        msg += f"📤 Ошибка SELL: {sell_res['error']}\n"
        
    bot.send_message(message.chat.id, msg, parse_mode="HTML")

if __name__ == '__main__':
    bot.infinity_polling()
