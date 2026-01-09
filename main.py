import telebot
from telebot import types
import json
import os
import time
import requests
from dotenv import load_dotenv # pip install python-dotenv

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')
PASSWORD = "130290"
DATA_FILE = 'p2p_db.json'

bot = telebot.TeleBot(TOKEN)

# --- БАЗА ДАННЫХ ---
def load_db():
    if not os.path.exists(DATA_FILE): return {}
    with open(DATA_FILE, 'r') as f: return json.load(f)

def save_db(data):
    with open(DATA_FILE, 'w') as f: json.dump(data, f, indent=4)

def is_auth(user_id):
    db = load_db()
    return db.get(str(user_id), {}).get('auth', False)

# --- МОНИТОРИНГ (Эмуляция) ---
# ВАЖНО: Мы используем публичный API Wallet P2P
def get_wallet_prices():
    try:
        # Это эндпоинт, который использует веб-версия Wallet
        url = "https://walletbot.me/api/v1/p2p/advertisements" 
        # Параметры фильтрации (UAH, USDT, Buy/Sell)
        # Примечание: Wallet часто меняет структуру, если упадет - нужно подправить заголовки
        params_buy = {"fiat": "UAH", "crypto": "USDT", "type": "BUY", "page": 1}
        params_sell = {"fiat": "UAH", "crypto": "USDT", "type": "SELL", "page": 1}
        
        # Для примера имитируем получение (так как реальный запрос требует Bearer токена)
        # В реальности здесь будет requests.get с заголовками
        return {"buy": 43.60, "sell": 46.10} 
    except:
        return None

# --- ОБРАБОТКА КОМАНД ---
@bot.message_handler(commands=['start'])
def start(message):
    if not is_auth(message.from_user.id):
        sent = bot.send_message(message.chat.id, "🔒 Доступ ограничен. Введите пароль:")
        bot.register_next_step_handler(sent, check_pass)
    else:
        main_menu(message)

def check_pass(message):
    if message.text == PASSWORD:
        db = load_db()
        db[str(message.from_user.id)] = {'auth': True, 'balance': 0, 'history': []}
        save_db(db)
        bot.send_message(message.chat.id, "✅ Доступ разрешен!")
        main_menu(message)
    else:
        sent = bot.send_message(message.chat.id, "❌ Неверно. Попробуй еще раз:")
        bot.register_next_step_handler(sent, check_pass)

def main_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📊 Калькулятор", "🔔 Мониторинг")
    markup.add("📈 История профита", "🛡 Безопасность")
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=markup)

# --- ЛОГИКА МОНИТОРИНГА ---
@bot.message_handler(func=lambda m: m.text == "🔔 Мониторинг")
def monitor_prices(message):
    prices = get_wallet_prices()
    if prices:
        spread = ((prices['sell'] * 0.991) / prices['buy'] - 1) * 100
        text = (f"🏦 **Wallet P2P Market**\n\n"
                f"📥 Лучший Buy: `{prices['buy']}`\n"
                f"📤 Лучший Sell: `{prices['sell']}`\n"
                f"🚀 Примерный спред: `{spread:.2f}%` (с учетом 0.9%)")
        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "⚠️ Не удалось получить данные. Попробуй позже.")

# --- ФУНКЦИЯ БЕЗОПАСНОСТИ ---
@bot.message_handler(func=lambda m: m.text == "🛡 Безопасность")
def safety_rules(message):
    rules = (
        "1️⃣ **Никогда** не подтверждай ордер, пока деньги не на счету (не верь скриншотам).\n"
        "2️⃣ Проверяй ФИО отправителя — оно должно совпадать с ФИО в Wallet.\n"
        "3️⃣ Не пиши комментарии к платежам в банке.\n"
        "4️⃣ Если упал подозрительный чек — делай возврат по реквизитам отправителя."
    )
    bot.send_message(message.chat.id, rules)

# --- КАЛЬКУЛЯТОР (Упрощенный ввод) ---
@bot.message_handler(func=lambda m: m.text == "📊 Калькулятор")
def calc_start(message):
    sent = bot.send_message(message.chat.id, "Введи данные через пробел:\n`Баланс КурсBuy КурсSell`\n\nПример: `3454 43.54 45.98`", parse_mode="Markdown")
    bot.register_next_step_handler(sent, fast_calc)

def fast_calc(message):
    try:
        parts = message.text.split()
        bal, buy, sell = float(parts[0]), float(parts[1]), float(parts[2])
        
        usdt = bal / buy
        clean_total = (usdt * sell) * 0.991
        profit = clean_total - bal
        
        res = (f"✅ Чистыми: `{clean_total:.2f} грн`\n"
               f"🤑 Профит: `{profit:.2f} грн` (`{ (profit/bal)*100 :.2f}%`)")
        
        # Сохраняем в историю
        db = load_db()
        db[str(message.from_user.id)]['history'].append({'date': time.time(), 'profit': profit})
        save_db(db)
        
        bot.send_message(message.chat.id, res, parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "⚠️ Ошибка. Формат: `3454 43.54 45.98`")

if __name__ == '__main__':
    bot.infinity_polling()
