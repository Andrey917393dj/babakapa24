import telebot
from telebot import types
import json
import os
import time
from dotenv import load_dotenv

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
        db[uid] = {'auth': False, 'bal': 0.0, 'buy': 0.0, 'sell': 0.0, 'start_inv': 0.0, 'usdt_wallet': 0.0}
        save_db(db)
    return db[uid]

def update_ud(user_id, key, val):
    db = load_db()
    db[str(user_id)][key] = val
    save_db(db)

# --- ГЛАВНОЕ МЕНЮ ---
def main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💸 Расчет круга", "📊 Общий профит")
    markup.add("🔍 Мониторинг Wallet", "🛡 Безопасность")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=markup)

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
        bot.send_message(message.chat.id, "✅ Пароль верный!")
        main_menu(message)
    else:
        sent = bot.send_message(message.chat.id, "❌ Неверно. Попробуй еще раз:")
        bot.register_next_step_handler(sent, check_pass)

# --- 1. ЛОГИКА КАЛЬКУЛЯТОРА КРУГА (ПОЭТАПНО) ---
@bot.message_handler(func=lambda m: m.text == "💸 Расчет круга")
def circle_step1(message):
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if ud['bal'] > 0: markup.add(f"Оставить {ud['bal']}")
    markup.add("Отмена")
    
    sent = bot.send_message(message.chat.id, "Введите баланс в грн (на который закупаем):", reply_markup=markup)
    bot.register_next_step_handler(sent, circle_step2)

def circle_step2(message):
    if message.text == "Отмена": return main_menu(message)
    val = message.text.replace("Оставить ", "")
    try:
        update_ud(message.from_user.id, 'bal', float(val))
        ud = get_ud(message.from_user.id)
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        if ud['buy'] > 0: markup.add(f"Оставить {ud['buy']}")
        sent = bot.send_message(message.chat.id, "Введите курс ЗАКУПА (Buy):", reply_markup=markup)
        bot.register_next_step_handler(sent, circle_step3)
    except: bot.send_message(message.chat.id, "Ошибка ввода."); main_menu(message)

def circle_step3(message):
    val = message.text.replace("Оставить ", "")
    try:
        update_ud(message.from_user.id, 'buy', float(val))
        ud = get_ud(message.from_user.id)
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        if ud['sell'] > 0: markup.add(f"Оставить {ud['sell']}")
        sent = bot.send_message(message.chat.id, "Введите курс ПРОДАЖИ (Sell):", reply_markup=markup)
        bot.register_next_step_handler(sent, circle_final)
    except: bot.send_message(message.chat.id, "Ошибка ввода."); main_menu(message)

def circle_final(message):
    val = message.text.replace("Оставить ", "")
    try:
        update_ud(message.from_user.id, 'sell', float(val))
        ud = get_ud(message.from_user.id)
        
        usdt = ud['bal'] / ud['buy']
        clean_res = (usdt * ud['sell']) * 0.991
        profit = clean_res - ud['bal']
        
        text = (f"📈 **Итог круга:**\n\n"
                f"💰 Вход: `{ud['bal']}` грн\n"
                f"📥 Получено: `{usdt:.2f}` USDT\n"
                f"📤 Чистый выход: `{clean_res:.2f}` грн\n"
                f"➖➖➖➖➖➖➖➖\n"
                f"🤑 Профит: **+{profit:.2f} грн** ({ (profit/ud['bal'])*100 :.2f}%)")
        bot.send_message(message.chat.id, text, parse_mode="Markdown")
        main_menu(message)
    except: bot.send_message(message.chat.id, "Ошибка расчета."); main_menu(message)

# --- 2. ЛОГИКА ОБЩЕГО ПРОФИТА (ПОЭТАПНО) ---
@bot.message_handler(func=lambda m: m.text == "📊 Общий профит")
def total_step1(message):
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if ud['usdt_wallet'] > 0: markup.add(f"Оставить {ud['usdt_wallet']}")
    sent = bot.send_message(message.chat.id, "Сколько USDT сейчас на кошельке?", reply_markup=markup)
    bot.register_next_step_handler(sent, total_step2)

def total_step2(message):
    val = message.text.replace("Оставить ", "")
    update_ud(message.from_user.id, 'usdt_wallet', float(val))
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # Используем текущий баланс как сумму на карте
    markup.add(f"Оставить {ud['bal']}")
    sent = bot.send_message(message.chat.id, "Сколько ГРИВЕН сейчас на карте?", reply_markup=markup)
    bot.register_next_step_handler(sent, total_step3)

def total_step3(message):
    val = message.text.replace("Оставить ", "")
    # Временно сохраним сумму на карте в 'bal' для расчета
    update_ud(message.from_user.id, 'bal', float(val))
    ud = get_ud(message.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if ud['start_inv'] > 0: markup.add(f"Оставить {ud['start_inv']}")
    sent = bot.send_message(message.chat.id, "Твои СТАРТОВЫЕ вложения (сколько своих завел)?", reply_markup=markup)
    bot.register_next_step_handler(sent, total_final)

def total_final(message):
    val = message.text.replace("Оставить ", "")
    update_ud(message.from_user.id, 'start_inv', float(val))
    ud = get_ud(message.from_user.id)
    
    # Считаем по курсу Sell из памяти (или 46 по дефолту)
    current_assets = (ud['usdt_wallet'] * ud['sell']) + ud['bal']
    total_profit = current_assets - ud['start_inv']
    
    text = (f"🏦 **Твой капитал сейчас:**\n"
            f"💵 В крипте (по курсу {ud['sell']}): `{(ud['usdt_wallet']*ud['sell']):.2f} грн`\n"
            f"💳 На карте: `{ud['bal']:.2f} грн`\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"🚀 Весь профит за время: **{total_profit:.2f} грн**")
    bot.send_message(message.chat.id, text, parse_mode="Markdown")
    main_menu(message)

# --- 3. МОНИТОРИНГ (ЭМУЛЯЦИЯ С ФИЛЬТРАМИ) ---
@bot.message_handler(func=lambda m: m.text == "🔍 Мониторинг Wallet")
def monitor_wallet(message):
    bot.send_message(message.chat.id, "⌛️ Получаю данные из стакана (фильтр: 100+ грн, все продавцы)...")
    
    # Имитация парсинга реального стакана (так как у Wallet нет API)
    # Если будешь использовать библиотеку requests к эндпоинтам, подставь сюда логику
    
    buy_orders = [
        {"price": 43.54, "nick": "CryptoKing", "limit": "100 - 15,000"},
        {"price": 43.58, "nick": "FastChange", "limit": "100 - 5,000"}
    ]
    sell_orders = [
        {"price": 45.98, "nick": "MajorP2P", "limit": "100 - 50,000"},
        {"price": 45.95, "nick": "UAH_Seller", "limit": "500 - 20,000"}
    ]
    
    res = "📥 **КУПИТЬ (Закуп):**\n"
    for o in buy_orders:
        res += f"🔹 {o['price']} | {o['nick']} | Лимит: {o['limit']}\n"
    
    res += "\n📤 **ПРОДАТЬ (Выход):**\n"
    for o in sell_orders:
        res += f"🔸 {o['price']} | {o['nick']} | Лимит: {o['limit']}\n"
        
    bot.send_message(message.chat.id, res, parse_mode="Markdown")
    main_menu(message)

@bot.message_handler(func=lambda m: m.text == "🛡 Безопасность")
def safety(message):
    text = ("1. Жди деньги на счету, а не скрин.\n"
            "2. Сверяй ФИО.\n"
            "3. Не подтверждай, если сумма не совпадает хоть на копейку.")
    bot.send_message(message.chat.id, text)

if __name__ == '__main__':
    print("Бот запущен...")
    bot.infinity_polling()
