import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import os

# Токен берём из поля на сайте, поэтому просто:
TOKEN = os.getenv("BOT_TOKEN")  # Bothost автоматически подставит токен из настроек

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# Интервал автопроверки (секунды)
CHECK_INTERVAL = 300  # 5 минут

# Кнопки
keyboard = InlineKeyboardMarkup(row_width=1)
keyboard.add(
    InlineKeyboardButton("🔄 Получить данные", callback_data="get_data")
)

# Заглушка функции для данных P2P
def get_wallet_data():
    return (
        "🟢 ПОКУПКА USDT (min 100 грн)\n"
        "1️⃣ 42.60 грн | лимит 100–20 000\n"
        "2️⃣ 42.65 грн | лимит 100–50 000\n\n"
        "🔴 ПРОДАЖА USDT (min 100 грн)\n"
        "1️⃣ 42.95 грн | лимит 100–10 000\n"
        "2️⃣ 42.90 грн | лимит 100–30 000"
    )

# Стартовое сообщение и кнопка
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "🤖 Wallet P2P Monitor запущен!\n\nНажми кнопку для получения данных.",
        reply_markup=keyboard
    )

# Кнопка "Получить данные"
@dp.callback_query_handler(lambda c: c.data == "get_data")
async def send_data(callback: types.CallbackQuery):
    data = get_wallet_data()
    await callback.message.answer(data)
    await callback.answer()

# Автопроверка каждые 5 минут (потом сюда можно вставить реальный парсер)
async def auto_checker():
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        # Сейчас просто заглушка, потом сюда будет реальный сбор данных
        # Например, можно отправлять себе сообщение с результатом
        # await bot.send_message(YOUR_CHAT_ID, get_wallet_data())
        # Для безопасности пока отключено

# Главная функция
async def main():
    asyncio.create_task(auto_checker())
    await dp.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
