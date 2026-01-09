import telebot
from telebot import types
import json
import os
import time
import threading
from dotenv import load_dotenv

# Загружаем переменные из .env или окружения сервера
load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')
PASSWORD = "130290"
DATA_FILE = 'p2p_db.json'

bot = telebot.TeleBot(TOKEN)

# --- РАБОТА С БАЗОЙ ---
def load_db():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)

def save_db(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)

def get_ud(user_id):
    db = load_db()
    uid = str(user_id)
    if uid not in db:
        db[uid] = {
            'auth': False, 
            'bal': 0.0, 
            'buy': 0.0, 
            'sell': 0.0, 
            'start_inv': 0.0, 
            'usdt_wallet': 0.0,
            'notifications': True # Включен ли авто-пинг
        }
        save_db(db)
    return db[uid]

def update_ud(user_id, key, val):
    db = load_db()
    db[str(user_id)][key] = val
    save_db(db)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💸 Расчет круга", "📊 Общий профит")
    markup.add("🔍 Мониторинг", "🔔 Уведомления: ON/OFF")
    markup.add("🛡 Безопасность")
    bot.send_message(message.chat.id, "<b>Главное меню:</b>", reply_markup=markup, parse_mode="HTML")

# --- ПРОВЕРКА ПАРОЛЯ ---
@bot.message_handler(commands=['start'])
def start(message):
    ud = get_ud(message.from_user.id)
    if not ud.get('auth'):
        sent = bot.send_message(message.chat.id, "🔒 Доступ ограничен. Введите пароль:")
        bot.register_next_step_handler(sent, check_pass)
    else:
        main_menu(message)

def check_pass(message):
    if message.text == PASSWORD:
        update_ud(message.from_user.id, 'auth', True)
        bot.send_message(message.chat.id, "✅ Доступ разрешен!")
        main_menu(message)
    else:
        sent = bot.send_message(message.chat.id, "❌ Неверно. Попробуй еще раз:")
        bot.register_next_step_handler(sent, check_pass)

# --- 1. РАСЧЕТ КРУГА (ПОЭТАПНО) ---
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def circle_step1(message):
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud['bal'] > 0: markup.add(f"Оставить {ud['bal']}")
    markup.add("Отмена")
    
    sent = bot.send_message(message.chat.id, "Введите баланс в <b>грн</b> (сумма закупа):", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(sent, circle_step2)

def circle_step2(message):
    if message.text == "Отмена": return main_menu(message)
    val = message.text.replace("Оставить ", "").replace(",", ".")
    try:
        update_ud(message.from_user.id, 'bal', float(val))
        ud = get_ud(message.from_user.id)
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        if ud['buy'] > 0: markup.add(f"Оставить {ud['buy']}")
        sent = bot.send_message(message.chat.id, "Введите курс <b>ЗАКУПА</b> (Buy):", reply_markup=markup, parse_mode="HTML")
        bot.register_next_step_handler(sent, circle_step3)
    except: bot.send_message(message.chat.id, "Ошибка. Вводи цифры."); main_menu(message)

def circle_step3(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    try:
        update_ud(message.from_user.id, 'buy', float(val))
        ud = get_ud(message.from_user.id)
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        if ud['sell'] > 0: markup.add(f"Оставить {ud['sell']}")
        sent = bot.send_message(message.chat.id, "Введите курс <b>ПРОДАЖИ</b> (Sell):", reply_markup=markup, parse_mode="HTML")
        bot.register_next_step_handler(sent, circle_final)
    except: bot.send_message(message.chat.id, "Ошибка."); main_menu(message)

def circle_final(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    try:
        update_ud(message.from_user.id, 'sell', float(val))
        ud = get_ud(message.from_user.id)
        
        usdt = ud['bal'] / ud['buy']
        clean_res = (usdt * ud['sell']) * 0.991
        profit = clean_res - ud['bal']
        
        text = (f"📈 <b>Итог круга:</b>\n\n"
                f"💰 Вход: <code>{ud['bal']:.2f}</code> грн\n"
                f"📥 Получено: <code>{usdt:.4f}</code> USDT\n"
                f"📤 Чистый выход: <b>{clean_res:.2f} грн</b>\n"
                f"➖➖➖➖➖➖➖➖\n"
                f"🤑 Профит: <b>+{profit:.2f} грн</b> ({ (profit/ud['bal'])*100 :.2f}%)")
        bot.send_message(message.chat.id, text, parse_mode="HTML")
        main_menu(message)
    except: bot.send_message(message.chat.id, "Ошибка расчета."); main_menu(message)

# --- 2. ОБЩИЙ ПРОФИТ (ПОЭТАПНО) ---
@bot.message_handler(func=lambda m: m.text == "📊 Общий профит")
def total_step1(message):
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if ud['usdt_wallet'] > 0: markup.add(f"Оставить {ud['usdt_wallet']}")
    sent = bot.send_message(message.chat.id, "Сколько <b>USDT</b> сейчас на кошельке?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(sent, total_step2)

def total_step2(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'usdt_wallet', float(val))
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(f"Оставить {ud['bal']}")
    sent = bot.send_message(message.chat.id, "Сколько <b>ГРИВЕН</b> сейчас на карте?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(sent, total_step3)

def total_step3(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'bal', float(val)) # Используем 'bal' как текущий кэш
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if ud['start_inv'] > 0: markup.add(f"Оставить {ud['start_inv']}")
    sent = bot.send_message(message.chat.id, "Твои <b>СТАРТОВЫЕ</b> вложения (свои деньги)?", reply_markup=markup, parse_mode="HTML")
    bot.register_next_step_handler(sent, total_final)

def total_final(message):
    val = message.text.replace("Оставить ", "").replace(",", ".")
    update_ud(message.from_user.id, 'start_inv', float(val))
    ud = get_ud(message.from_user.id)
    
    current_assets = (ud['usdt_wallet'] * ud['sell']) + ud['bal']
    total_profit = current_assets - ud['start_inv']
    
    text = (f"🏦 <b>Твой капитал сейчас:</b>\n\n"
            f"💵 В крипте (по {ud['sell']}): <code>{(ud['usdt_wallet']*ud['sell']):.2f} грн</code>\n"
            f"💳 На карте: <code>{ud['bal']:.2f} грн</code>\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"🚀 Весь профит за время: <b>{total_profit:.2f} грн</b>")
    bot.send_message(message.chat.id, text, parse_mode="HTML")
    main_menu(message)

# --- 3. МОНИТОРИНГ (БЕЗ ОШИБОК) ---
@bot.message_handler(func=lambda m: m.text == "🔍 Мониторинг")
def monitor_command(message):
    prices = fetch_prices()
    res = format_prices(prices)
    bot.send_message(message.chat.id, res, parse_mode="HTML")

def fetch_prices():
    # Мок-данные (сюда можно вставить реальный парсинг через requests)
    return {
        "buy": [
            {"p": 43.54, "n": "Crypto_King", "l": "100-15k"},
            {"p": 43.58, "n": "P2P_Pro", "l": "100-5k"}
        ],
        "sell": [
            {"p": 45.98, "n": "UAH_Seller", "l": "100-50k"},
            {"p": 45.95, "n": "Mister_X", "l": "500-20k"}
        ]
    }

def format_prices(data):
    res = "📥 <b>КУПИТЬ (Закуп):</b>\n"
    for o in data['buy']:
        res += f"• {o['p']} | {o['n']} | Лимит: {o['l']}\n"
    res += "\n📤 <b>ПРОДАТЬ (Выход):</b>\n"
    for o in data['sell']:
        res += f"• {o['p']} | {o['n']} | Лимит: {o['l']}\n"
    return res

# --- АВТО-МОНИТОРИНГ В ФОНЕ (24/7) ---
def auto_monitor():
    while True:
        try:
            db = load_db()
            prices = fetch_prices()
            best_buy = prices['buy'][0]['p']
            best_sell = prices['sell'][0]['p']
            spread = ((best_sell * 0.991) / best_buy - 1) * 100
            
            if spread >= 3.0:
                for uid, data in db.items():
                    if data.get('auth') and data.get('notifications'):
                        msg = f"🔔 <b>ЖИРНЫЙ СПРЕД: {spread:.2f}%</b>\n\n" + format_prices(prices)
                        bot.send_message(uid, msg, parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка мониторинга: {e}")
        time.sleep(60) # Проверка раз в минуту

@bot.message_handler(func=lambda m: m.text == "🔔 Уведомления: ON/OFF")
def toggle_notify(message):
    ud = get_ud(message.from_user.id)
    new_status = not ud.get('notifications', True)
    update_ud(message.from_user.id, 'notifications', new_status)
    status_text = "ВКЛЮЧЕНЫ" if new_status else "ВЫКЛЮЧЕНЫ"
    bot.send_message(message.chat.id, f"🔔 Уведомления теперь: <b>{status_text}</b>", parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🛡 Безопасность")
def safety(message):
    text = "<b>Правила P2P:</b>\n1. Деньги только на счету (не чек).\n2. Сверяй ФИО.\n3. Не верь поддержке в чате ордера."
    bot.send_message(message.chat.id, text, parse_mode="HTML")

if __name__ == '__main__':
    # Запуск фонового потока
    threading.Thread(target=auto_monitor, daemon=True).start()
    print("Бот и Мониторинг запущены...")
    bot.infinity_polling()
